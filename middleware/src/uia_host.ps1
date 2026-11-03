<#
  src/uia_host.ps1 —— Tier1 稀疏 UIA 常驻宿主（独立进程 = 可被硬杀的超时熔断边界）

  为什么用 PowerShell/C#：
    本机没有 comtypes / pywin32 / uiautomation，安装需联网（违反离线约束）。
    .NET Framework 自带 UIAutomationClient（CacheRequest 能力完整），无需任何安装。
    用常驻子进程而不是每次新起进程，避免每次 300ms+ 的启动开销；
    进程隔离让“卡死的 COM 调用”可以被 kill 掉，这是 Python 线程做不到的。

  协议（stdin/stdout，UTF-8，一行一条）：
    请求：  hwnd,max_items,depth       例如 1234567,10,2
    响应：  {"ok":true,"t_us":...,"fh_us":...,"n":...,"seen":...,"c":...,"trunc":0,"items":[...]}
    就绪：  {"ready":true}              编译完成后打印一次

  实测坑（Win10 记事本）：编辑框在 UIA 里是 ControlType.Pane + ClassName=Edit（MSAA 桥接），
  只按 ControlType 过滤会 0 命中 —— 因此同时按 class 名兜底。
#>
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName WindowsBase

$code = @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text;
using System.Threading;
using System.Windows;
using System.Windows.Automation;

public static class UiaServer
{
    private static readonly HashSet<string> Actionable = new HashSet<string>(StringComparer.Ordinal) {
        "Button","Edit","CheckBox","ComboBox","RadioButton","MenuItem","Hyperlink","ListItem",
        "TabItem","SplitButton","Slider","Spinner","DataItem","TreeItem","Document"
    };
    private static readonly HashSet<string> ByClass = new HashSet<string>(StringComparer.Ordinal) {
        "Edit","Button","ComboBox","RichEdit20W","RichEdit50W","RICHEDIT60W"
    };
    private static readonly HashSet<string> Container = new HashSet<string>(StringComparer.Ordinal) {
        "Pane","Group","Window","ToolBar","Custom","Document","List","DataGrid"
    };

    public static void Run()
    {
        Thread t = new Thread(new ThreadStart(Loop));
        t.SetApartmentState(ApartmentState.MTA);
        t.IsBackground = false;
        t.Start();
        t.Join();
    }

    private static void Loop()
    {
        Console.Out.WriteLine("{\"ready\":true}");
        Console.Out.Flush();
        while (true)
        {
            string line;
            try { line = Console.In.ReadLine(); }
            catch { break; }
            if (line == null) break;
            line = line.Trim();
            if (line.Length == 0) continue;
            string resp;
            try { resp = Handle(line); }
            catch (Exception ex) { resp = "{\"ok\":false,\"e\":\"" + Esc(ex.GetType().Name + ": " + ex.Message) + "\"}"; }
            Console.Out.WriteLine(resp);
            Console.Out.Flush();
        }
    }

    private static string Handle(string req)
    {
        string[] p = req.Split(',');
        int hwnd = int.Parse(p[0]);
        int maxItems = p.Length > 1 ? int.Parse(p[1]) : 10;
        int depth = p.Length > 2 ? int.Parse(p[2]) : 2;
        bool wantText = p.Length > 3 && int.Parse(p[3]) == 1;
        bool deep = p.Length > 4 && int.Parse(p[4]) == 1;
        string targetId = p.Length > 5 ? p[5].Trim() : "";
        if (targetId == "-") targetId = "";
        // 可选字段 7/8：页面锚点（屏幕坐标）。>0 时启用“hit-test -> 页面 Document -> 子树”路径，
        // 用来跨越 Chromium 渲染边界（浏览器窗口的 Descendants 枚举到不了网页内容）。
        int ax = p.Length > 6 ? int.Parse(p[6].Trim()) : 0;
        int ay = p.Length > 7 ? int.Parse(p[7].Trim()) : 0;
        // 可选字段 9：focus=1 时只返回当前焦点控件（验证读回用，不枚举任何子树）
        bool focusMode = p.Length > 8 && int.Parse(p[8].Trim()) == 1;

        Stopwatch sw = Stopwatch.StartNew();
        AutomationElement root = (hwnd != 0)
            ? AutomationElement.FromHandle(new IntPtr(hwnd))
            : AutomationElement.FocusedElement;
        if (root == null) return "{\"ok\":false,\"e\":\"root-null\"}";
        long fh = (long)(sw.Elapsed.TotalMilliseconds * 1000.0);

        CacheRequest cr = new CacheRequest();
        cr.Add(AutomationElement.NameProperty);
        cr.Add(AutomationElement.ControlTypeProperty);
        cr.Add(AutomationElement.ClassNameProperty);
        cr.Add(AutomationElement.BoundingRectangleProperty);
        cr.Add(AutomationElement.IsEnabledProperty);
        cr.Add(AutomationElement.IsOffscreenProperty);
        cr.Add(AutomationElement.AutomationIdProperty);
        try { cr.Add(AutomationProperty.LookupById(30045)); } catch { }   // UIA_ValueValuePropertyId
        cr.TreeFilter = new PropertyCondition(AutomationElement.IsControlElementProperty, true);

        List<string> items = new List<string>();
        int seen = 0;
        int containers = 0;
        bool truncated = false;

        using (cr.Activate())
        {
            if (focusMode)
            {
                // 焦点读回：只取 FocusedElement 一个元素（不枚举任何子树）
                AutomationElement f = null;
                try { f = AutomationElement.FocusedElement; } catch { }
                if (f == null) return "{\"ok\":false,\"e\":\"focus-null\"}";
                sw.Stop();
                long tf = (long)(sw.Elapsed.TotalMilliseconds * 1000.0);
                StringBuilder fb = new StringBuilder(256);
                fb.Append("{\"ok\":true,\"t_us\":").Append(tf)
                  .Append(",\"fh_us\":").Append(fh)
                  .Append(",\"n\":1,\"seen\":1,\"c\":0,\"deep\":1,\"focus\":1,\"items\":[")
                  .Append(Item(f, wantText, "focus")).Append("]}");
                return fb.ToString();
            }
            if (deep)
            {
                // 页面模式：先按锚点命中 -> 向上找到页面 Document（Chromium: AutomationId=RootWebArea），
                // 再从 Document 枚举。浏览器窗口根节点的 Descendants 会在渲染边界处变成空桩，
                // 这条路径是唯一能拿到网页内控件的原生 UIA 通道。
                bool pageOk = false;
                string docId = "";
                int dx = 0, dy = 0, dw = 0, dh = 0;
                int pageSeen = 0;
                bool havePageEdit = false;
                if (ax > 0 && ay > 0)
                {
                    AutomationElement doc = null;
                    try
                    {
                        AutomationElement cur = AutomationElement.FromPoint(new Point(ax, ay));
                        for (int up = 0; up < 12 && cur != null; up++)
                        {
                            // 注意：TreeWalker 返回的元素不在 CacheRequest 缓存里，必须走 Current.*
                            if (IdCur(cur) == "RootWebArea" || TypeCur(cur) == "Document") { doc = cur; break; }
                            try { cur = TreeWalker.ControlViewWalker.GetParent(cur); } catch { cur = null; }
                        }
                    }
                    catch { }
                    if (doc != null)
                    {
                        pageOk = true;
                        docId = IdCur(doc);
                        Rect dr = Rect.Empty;
                        try { dr = doc.Current.BoundingRectangle; } catch { }
                        if (dr != Rect.Empty && !double.IsInfinity(dr.Width) && !double.IsInfinity(dr.Height)
                            && dr.Width > 0 && dr.Height > 0)
                        {
                            dx = (int)dr.X; dy = (int)dr.Y; dw = (int)dr.Width; dh = (int)dr.Height;
                        }
                        AutomationElementCollection pall = doc.FindAll(TreeScope.Descendants, Condition.TrueCondition);
                        pageSeen = pall.Count;
                        foreach (AutomationElement e in pall)
                        {
                            if (e == null) continue;
                            if (EffectiveType(e) != "Edit") continue;
                            if (items.Count >= maxItems) { truncated = true; break; }
                            items.Add(Item(e, wantText, "page"));
                            havePageEdit = true;
                        }
                    }
                }
                // 深查（只给“按 id 解析目标”用）：一次 Descendants 查询 + 缓存，按元素数封顶
                AutomationElementCollection all = root.FindAll(TreeScope.Descendants, Condition.TrueCondition);
                int scanned = 0;
                foreach (AutomationElement e in all)
                {
                    if (e == null) continue;
                    scanned++;
                    seen++;
                    if (scanned > 600) { truncated = true; break; }
                    if (targetId.Length > 0)
                    {
                        if (IdOf(e) == targetId)
                        {
                            items.Add(Item(e, wantText, "win"));
                            break;
                        }
                        continue;   // 指定 id 时只返回该元素（验证/读回用）
                    }
                    if (IsActionable(e))
                    {
                        // 页面模式下，窗口枚举里那个 0 尺寸的 Edit 是渲染边界的空桩，丢掉
                        if (havePageEdit && EffectiveType(e) == "Edit" && EmptyRect(e)) continue;
                        if (items.Count >= maxItems) { truncated = true; break; }
                        items.Add(Item(e, wantText, "win"));
                    }
                }
                sw.Stop();
                long td = (long)(sw.Elapsed.TotalMilliseconds * 1000.0);
                StringBuilder sb2 = new StringBuilder(256);
                sb2.Append("{\"ok\":true,\"t_us\":").Append(td)
                   .Append(",\"fh_us\":").Append(fh)
                   .Append(",\"n\":").Append(items.Count)
                   .Append(",\"seen\":").Append(seen)
                   .Append(",\"c\":0,\"deep\":1,\"trunc\":").Append(truncated ? 1 : 0)
                   .Append(",\"page\":").Append(pageOk ? 1 : 0)
                   .Append(",\"doc_id\":\"").Append(Esc(docId)).Append("\"")
                   .Append(",\"doc_rect\":[").Append(dx).Append(',').Append(dy).Append(',')
                   .Append(dw).Append(',').Append(dh).Append("]")
                   .Append(",\"page_seen\":").Append(pageSeen)
                   .Append(",\"items\":[");
                for (int i = 0; i < items.Count; i++)
                {
                    if (i > 0) sb2.Append(',');
                    sb2.Append(items[i]);
                }
                sb2.Append("]}");
                return sb2.ToString();
            }

            AutomationElementCollection kids = root.FindAll(TreeScope.Children, Condition.TrueCondition);
            foreach (AutomationElement k in kids)
            {
                if (k == null) continue;
                seen++;
                string ctype = TypeOf(k);
                if (depth >= 2 && containers < 4 && Container.Contains(ctype))
                {
                    containers++;
                    AutomationElementCollection gk = k.FindAll(TreeScope.Children, Condition.TrueCondition);
                    foreach (AutomationElement e in gk)
                    {
                        if (e == null) continue;
                        seen++;
                        if (IsActionable(e))
                        {
                            if (items.Count >= maxItems) { truncated = true; break; }
                            items.Add(Item(e, wantText, "win"));
                        }
                    }
                }
                if (items.Count >= maxItems) { truncated = true; break; }
                if (IsActionable(k)) items.Add(Item(k, wantText, "win"));
            }
        }

        sw.Stop();
        long total = (long)(sw.Elapsed.TotalMilliseconds * 1000.0);
        StringBuilder sb = new StringBuilder(256);
        sb.Append("{\"ok\":true,\"t_us\":").Append(total)
          .Append(",\"fh_us\":").Append(fh)
          .Append(",\"n\":").Append(items.Count)
          .Append(",\"seen\":").Append(seen)
          .Append(",\"c\":").Append(containers)
          .Append(",\"trunc\":").Append(truncated ? 1 : 0)
          .Append(",\"items\":[");
        for (int i = 0; i < items.Count; i++)
        {
            if (i > 0) sb.Append(',');
            sb.Append(items[i]);
        }
        sb.Append("]}");
        return sb.ToString();
    }

    private static string TypeOf(AutomationElement e)
    {
        try
        {
            ControlType ct = e.Cached.ControlType;
            if (ct == null) return "";
            string n = ct.ProgrammaticName;
            int idx = n.LastIndexOf('.');
            return idx >= 0 ? n.Substring(idx + 1) : n;
        }
        catch { return ""; }
    }

    private static string ClassOf(AutomationElement e)
    {
        try { return e.Cached.ClassName ?? ""; } catch { return ""; }
    }

    private static string IdOf(AutomationElement e)
    {
        try { return e.Cached.AutomationId ?? ""; } catch { return ""; }
    }

    // Current.* 版本：给 TreeWalker / FromPoint 拿到的元素用（它们不进 CacheRequest 缓存）
    private static string IdCur(AutomationElement e)
    {
        try { return e.Current.AutomationId ?? ""; } catch { return ""; }
    }

    private static string TypeCur(AutomationElement e)
    {
        try
        {
            ControlType ct = e.Current.ControlType;
            if (ct == null) return "";
            string n = ct.ProgrammaticName;
            int idx = n.LastIndexOf('.');
            return idx >= 0 ? n.Substring(idx + 1) : n;
        }
        catch { return ""; }
    }

    private static bool IsActionable(AutomationElement e)
    {
        string ct = TypeOf(e);
        if (Actionable.Contains(ct)) return true;
        return ByClass.Contains(ClassOf(e));
    }

    private static string EffectiveType(AutomationElement e)
    {
        string ct = TypeOf(e);
        string cl = ClassOf(e);
        if (!Actionable.Contains(ct) && ByClass.Contains(cl))
        {
            if (cl.StartsWith("Edit") || cl.StartsWith("RICHEDIT") || cl.StartsWith("RichEdit")) return "Edit";
            return cl;
        }
        return ct;
    }

    private static bool EmptyRect(AutomationElement e)
    {
        try
        {
            Rect r = e.Cached.BoundingRectangle;
            return (r == Rect.Empty || r.Width <= 0 || r.Height <= 0
                    || double.IsInfinity(r.Width) || double.IsInfinity(r.Height));
        }
        catch { return true; }
    }

    private static string Item(AutomationElement e, bool wantText, string src)
    {
        string name = "";
        string aid = "";
        Rect r = Rect.Empty;
        bool en = true;
        bool off = false;
        try { name = e.Cached.Name ?? ""; } catch { }
        try { aid = e.Cached.AutomationId ?? ""; } catch { }
        try { r = e.Cached.BoundingRectangle; } catch { }
        try { en = e.Cached.IsEnabled; } catch { }
        try { off = e.Cached.IsOffscreen; } catch { }

        int x = 0, y = 0, w = 0, h = 0;
        if (r != Rect.Empty && !double.IsInfinity(r.Width) && !double.IsInfinity(r.Height)
            && r.Width > 0 && r.Height > 0)
        {
            x = (int)r.X; y = (int)r.Y; w = (int)r.Width; h = (int)r.Height;
        }
        if (name.Length > 40) name = name.Substring(0, 40);
        if (aid.Length > 32) aid = aid.Substring(0, 32);

        string val = "";
        try
        {
            object o = e.GetCachedPropertyValue(AutomationProperty.LookupById(30045));
            if (o is string) val = (string)o;
        }
        catch { }

        // 只有显式要求（wantText=1）才走 TextPattern：它会触发一次跨进程调用，不能放进常规感知路径
        if (wantText)
        {
            try
            {
                object tpObj = e.GetCurrentPattern(TextPattern.Pattern);
                TextPattern tp = tpObj as TextPattern;
                if (tp != null)
                {
                    string t = tp.DocumentRange.GetText(-1);
                    if (!string.IsNullOrEmpty(t)) val = t;
                }
            }
            catch { }
        }
        int cap = wantText ? 2000 : 80;   // 验证查询保留全文；常规感知查询仍压到 80 字
        if (val.Length > cap) val = val.Substring(0, cap);

        return "{\"t\":\"" + Esc(EffectiveType(e)) + "\",\"n\":\"" + Esc(name) + "\",\"r\":["
             + x + "," + y + "," + w + "," + h + "],\"e\":" + (en ? 1 : 0)
             + ",\"o\":" + (off ? 1 : 0) + ",\"id\":\"" + Esc(aid) + "\",\"v\":\"" + Esc(val)
             + "\",\"src\":\"" + Esc(src) + "\"}";
    }

    private static string Esc(string s)
    {
        if (string.IsNullOrEmpty(s)) return "";
        StringBuilder b = new StringBuilder(s.Length + 8);
        foreach (char c in s)
        {
            if (c == '"' || c == '\\') { b.Append('\\').Append(c); }
            else if (c == '\n' || c == '\r' || c == '\t') b.Append(' ');
            else if (c < 32) { }
            else b.Append(c);
        }
        return b.ToString();
    }
}
'@

# 编译一次、缓存成 DLL：Add-Type -TypeDefinition 每次启动都要跑一遍 csc（实测 ~3.5s）。
# 宿主被 40ms 硬档熔断后需要重启，这 3.5s 就是“控制级画像”的盲区（R4），所以这里改为
# 首次编译并 -OutputAssembly 落盘，之后直接 -Path 加载（实测 ~0.4s）。
$scriptPath = $MyInvocation.MyCommand.Path
$dllPath = Join-Path (Split-Path -Parent $scriptPath) "uia_host.dll"
$needBuild = $true
if (Test-Path $dllPath) {
    try {
        $needBuild = (Get-Item $dllPath).LastWriteTimeUtc -lt (Get-Item $scriptPath).LastWriteTimeUtc
    } catch { $needBuild = $true }
}
$loaded = $false
if (-not $needBuild) {
    try { Add-Type -Path $dllPath; $loaded = $true } catch { $loaded = $false }
}
if (-not $loaded) {
    try {
        Add-Type -TypeDefinition $code -ReferencedAssemblies @(
            [System.Windows.Automation.AutomationElement].Assembly.Location,
            [System.Windows.Automation.AutomationProperty].Assembly.Location,
            [System.Windows.Rect].Assembly.Location
        ) -OutputAssembly $dllPath
        Add-Type -Path $dllPath
    } catch {
        # 落盘失败（例如旧宿主还锁着 DLL）就退回内存编译，功能不受影响
        Add-Type -TypeDefinition $code -ReferencedAssemblies @(
            [System.Windows.Automation.AutomationElement].Assembly.Location,
            [System.Windows.Automation.AutomationProperty].Assembly.Location,
            [System.Windows.Rect].Assembly.Location
        )
    }
}

[UiaServer]::Run()
