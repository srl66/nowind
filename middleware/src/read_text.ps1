param([long]$Hwnd, [int]$MaxChars = 4000)

# 用 UIA TextPattern 直接读取文档正文，不选全、不复制、不动剪贴板。
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

function Fail([string]$Reason) {
  $o = @{ ok = $false; reason = $Reason; text = ""; chars = 0 }
  [Console]::Out.WriteLine(($o | ConvertTo-Json -Compress))
  exit 0
}

try {
  $root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Hwnd)
  if ($null -eq $root) { Fail "no-window" }

  $docCond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Document)
  $doc = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $docCond)
  if ($null -eq $doc) {
    $focus = [System.Windows.Automation.AutomationElement]::FocusedElement
    if ($null -ne $focus) { $doc = $focus } else { $doc = $root }
  }

  $tp = $doc.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
  if ($null -eq $tp) { Fail "no-text-pattern" }

  $raw = $tp.DocumentRange.GetText($MaxChars)
  $text = ""
  if ($null -ne $raw) { $text = $raw.Trim() }
  if ($text.Length -eq 0) { Fail "empty-text" }

  $o = @{ ok = $true; reason = ""; chars = $text.Length; text = $text }
  [Console]::Out.WriteLine(($o | ConvertTo-Json -Compress))
} catch {
  Fail ("exception:" + $_.Exception.GetType().Name)
}
