param([long]$Hwnd, [int]$MaxItems = 60)

# UIA 兜底探测：Raw View + 悬停 FromPoint + MSAA/IAccessible。
# 只在正常 UIA 深层读屏找不到目标时调用；会短暂移动鼠标，结束前恢复原位。
$ErrorActionPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName Accessibility
Add-Type -AssemblyName WindowsBase
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class FbNative {
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
  [DllImport("oleacc.dll")] public static extern int AccessibleObjectFromWindow(
    IntPtr hwnd, uint dwId, ref Guid riid,
    [MarshalAs(UnmanagedType.IUnknown)] out object ppvObject);
}
'@

$script:items = New-Object System.Collections.ArrayList
$script:seen = @{}

function Add-Item([string]$t, [string]$n, $r, [string]$src) {
  if ($script:items.Count -ge $MaxItems) { return }
  $key = "$t|$n|$($r[0])|$($r[1])|$($r[2])|$($r[3])"
  if ($script:seen.ContainsKey($key)) { return }
  $script:seen[$key] = $true
  [void]$script:items.Add(@{ t = $t; n = $n; r = @([int]$r[0], [int]$r[1], [int]$r[2], [int]$r[3]); src = $src })
}

function Uia-Info($e, [string]$src) {
  try {
    $ct = $e.Current.ControlType.ProgrammaticName -replace '^ControlType\.', ''
    $nm = [string]$e.Current.Name
    if ($nm.Length -gt 40) { $nm = $nm.Substring(0, 40) }
    $rc = $e.Current.BoundingRectangle
    if ($rc.IsEmpty -or $rc.Width -le 0 -or $rc.Height -le 0) { return }
    Add-Item $ct $nm @([int]$rc.X, [int]$rc.Y, [int]$rc.Width, [int]$rc.Height) $src
  } catch {}
}

$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Hwnd)
if ($null -eq $root) {
  @{ ok = $false; reason = "no-window"; items = @() } | ConvertTo-Json -Compress -Depth 5
  exit 0
}

# 1) Raw View：Control View 会过滤掉的自绘/分组节点
try {
  $all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
  for ($i = 0; $i -lt $all.Count -and $script:items.Count -lt $MaxItems; $i++) {
    Uia-Info $all.Item($i) "raw"
  }
} catch {}

# 2) 悬停 + FromPoint：覆盖“鼠标移上去才创建”的按钮
$orig = New-Object FbNative+POINT
[void][FbNative]::GetCursorPos([ref]$orig)
try {
  $wr = $root.Current.BoundingRectangle
  for ($ix = 1; $ix -le 4; $ix++) {
    for ($iy = 1; $iy -le 4; $iy++) {
      if ($script:items.Count -ge $MaxItems) { break }
      $x = [int]($wr.X + $wr.Width * $ix / 5.0)
      $y = [int]($wr.Y + $wr.Height * $iy / 5.0)
      [void][FbNative]::SetCursorPos($x, $y)
      Start-Sleep -Milliseconds 120
      try {
        $e = [System.Windows.Automation.AutomationElement]::FromPoint((New-Object System.Windows.Point -ArgumentList $x, $y))
        if ($null -ne $e) { Uia-Info $e "point" }
      } catch {}
    }
  }
  # 右侧一列：列表条目的“…”常在右上角
  for ($iy = 1; $iy -le 4; $iy++) {
    if ($script:items.Count -ge $MaxItems) { break }
    $x = [int]($wr.X + $wr.Width * 0.9)
    $y = [int]($wr.Y + $wr.Height * $iy / 5.0)
    [void][FbNative]::SetCursorPos($x, $y)
    Start-Sleep -Milliseconds 150
    try {
      $e = [System.Windows.Automation.AutomationElement]::FromPoint((New-Object System.Windows.Point -ArgumentList $x, $y))
      if ($null -ne $e) { Uia-Info $e "point-right" }
    } catch {}
  }
} finally {
  [void][FbNative]::SetCursorPos($orig.X, $orig.Y)
}

# 3) MSAA / IAccessible：UIA 之前的底层无障碍接口
function Walk-Acc($a, [int]$depth) {
  if ($script:items.Count -ge $MaxItems -or $depth -gt 3) { return }
  try {
    $nm = [string]$a.accName(0)
    if ($nm.Length -gt 40) { $nm = $nm.Substring(0, 40) }
    $role = [string]$a.accRole(0)
    $l = 0; $t = 0; $w = 0; $h = 0
    $a.accLocation([ref]$l, [ref]$t, [ref]$w, [ref]$h, 0) | Out-Null
    if ($w -gt 0 -and $h -gt 0) { Add-Item "msaa:$role" $nm @($l, $t, $w, $h) "msaa" }
  } catch {}
  try {
    $cnt = [int]$a.accChildCount
    for ($i = 1; $i -le $cnt -and $script:items.Count -lt $MaxItems; $i++) {
      try {
        $c = $a.accChild($i)
        if ($null -ne $c -and $c -is [Accessibility.IAccessible]) { Walk-Acc $c ($depth + 1) }
      } catch {}
    }
  } catch {}
}

try {
  $iid = [Guid]"618736E0-3C3D-11CF-810C-00AA00389B71"
  $acc = $null
  $hr = [FbNative]::AccessibleObjectFromWindow([IntPtr]$Hwnd, [uint32]4294967292, [ref]$iid, [ref]$acc)
  if ($hr -eq 0 -and $null -ne $acc) { Walk-Acc $acc 0 }
} catch {}

$out = @{ ok = $true; hwnd = [int]$Hwnd; count = $script:items.Count; items = $script:items }
[Console]::Out.WriteLine(($out | ConvertTo-Json -Compress -Depth 6))
