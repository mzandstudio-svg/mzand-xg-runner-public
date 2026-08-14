$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class XGF {
  public const uint PROCESS_QUERY_INFORMATION=0x0400, PROCESS_VM_READ=0x0010, MEM_COMMIT=0x1000;
  [StructLayout(LayoutKind.Sequential)] public struct MBI {
    public IntPtr BaseAddress, AllocationBase; public uint AllocationProtect;
    public UIntPtr RegionSize; public uint State, Protect, Type;
  }
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
  [DllImport("kernel32.dll",SetLastError=true)] public static extern IntPtr OpenProcess(uint a,bool i,int pid);
  [DllImport("kernel32.dll",SetLastError=true)] public static extern bool ReadProcessMemory(IntPtr h,IntPtr a,byte[] b,UIntPtr n,out UIntPtr got);
  [DllImport("kernel32.dll")] public static extern int VirtualQueryEx(IntPtr h,IntPtr a,out MBI m,uint n);
  [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr hMenu,int p);
  [DllImport("user32.dll")] public static extern bool GetMenuItemRect(IntPtr hWnd,IntPtr hMenu,uint item,out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
  public static int[] Search4(byte[] h, byte[] n) {
    var a=new List<int>();
    if(n.Length==0 || h.Length<n.Length) return a.ToArray();
    int anchor=91; byte av=n[anchor]; int lim=h.Length-n.Length;
    for(int i=0;i<=lim;i+=4) {
      if(h[i+anchor]!=av) continue;
      bool ok=true;
      for(int j=0;j<n.Length;j++) if(h[i+j]!=n[j]) { ok=false; break; }
      if(ok) a.Add(i);
    }
    return a.ToArray();
  }
}
"@

function Test-Readable([uint32]$p) {
  if (($p -band 0x100) -ne 0 -or ($p -band 0x01) -ne 0) { return $false }
  return (($p -band 0x02) -ne 0 -or ($p -band 0x04) -ne 0 -or ($p -band 0x08) -ne 0 -or
          ($p -band 0x10) -ne 0 -or ($p -band 0x20) -ne 0 -or ($p -band 0x40) -ne 0 -or ($p -band 0x80) -ne 0)
}
function Hex([UInt64]$x) { return ('0x{0:X8}' -f $x) }
function ClickXY([int]$x,[int]$y) {
  [XGF]::SetCursorPos($x,$y) | Out-Null
  Start-Sleep -Milliseconds 60
  [XGF]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 40
  [XGF]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}

$pattern=[Convert]::FromBase64String('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgD8AAIA/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIA/AACAPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIA/AACAPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgD8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAPwAAgD8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgD8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=')
if ($pattern.Length -ne 800) { throw "bad C00 pattern length $($pattern.Length)" }

$xg=Get-Process eXtremeGammon2 -ErrorAction Stop | Select-Object -First 1
$xg.Refresh()
if ($xg.MainWindowTitle -notlike '*Position.xgp*') { throw "Position not ready: $($xg.MainWindowTitle)" }
$out=Join-Path $env:GITHUB_WORKSPACE 'xg-input-probe-v3'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$report=Join-Path $out 'report.txt'
"PID=$($xg.Id)" | Out-File $report
"TITLE=$($xg.MainWindowTitle)" | Out-File $report -Append

$access=[XGF]::PROCESS_QUERY_INFORMATION -bor [XGF]::PROCESS_VM_READ
$h=[XGF]::OpenProcess($access,$false,$xg.Id)
if ($h -eq [IntPtr]::Zero) { throw 'OpenProcess failed' }

function Scan-C00([string]$label) {
  $hits=New-Object 'System.Collections.Generic.List[object]'
  $addr=[UInt64]0x10000
  $max=[UInt64]0x7FFEFFFF
  $overlap=$pattern.Length-1
  while ($addr -lt $max) {
    $m=New-Object XGF+MBI
    $q=[XGF]::VirtualQueryEx($h,[IntPtr]([Int64]$addr),[ref]$m,[uint32][Runtime.InteropServices.Marshal]::SizeOf([type]'XGF+MBI'))
    if ($q -eq 0) { break }
    $rb=[UInt64]$m.BaseAddress.ToInt64()
    $rs=[UInt64]$m.RegionSize.ToUInt64()
    if ($rs -eq 0) { break }
    $re=$rb+$rs
    if ($m.State -eq [XGF]::MEM_COMMIT -and (Test-Readable $m.Protect) -and $rs -ge 800 -and $rs -le 268435456) {
      $cursor=$rb
      $carry=New-Object byte[] 0
      while ($cursor -lt $re) {
        $want=[int][Math]::Min(8388608.0,[double]($re-$cursor))
        $buf=New-Object byte[] $want
        $got=[UIntPtr]::Zero
        $ok=[XGF]::ReadProcessMemory($h,[IntPtr]([Int64]$cursor),$buf,[UIntPtr]([UInt64]$want),[ref]$got)
        $n=[int]$got.ToUInt64()
        if (-not $ok -or $n -le 0) { break }
        if ($n -ne $buf.Length) {
          $b2=New-Object byte[] $n
          [Array]::Copy($buf,$b2,$n)
          $buf=$b2
        }
        $combined=New-Object byte[] ($carry.Length+$buf.Length)
        if ($carry.Length -gt 0) { [Array]::Copy($carry,0,$combined,0,$carry.Length) }
        [Array]::Copy($buf,0,$combined,$carry.Length,$buf.Length)
        foreach ($offset in [XGF]::Search4($combined,$pattern)) {
          $va=[UInt64]([Int64]$cursor-[Int64]$carry.Length+[Int64]$offset)
          $vec=New-Object byte[] (252*4)
          $got2=[UIntPtr]::Zero
          [void][XGF]::ReadProcessMemory($h,[IntPtr]([Int64]$va),$vec,[UIntPtr]([UInt64]$vec.Length),[ref]$got2)
          $csv=Join-Path $out ("{0}-{1:X8}.csv" -f $label,$va)
          'index,value,bits' | Out-File $csv
          for ($k=0; $k -lt 252 -and ($k*4+4) -le $got2.ToUInt64(); $k++) {
            $fv=[BitConverter]::ToSingle($vec,$k*4)
            $bits=[BitConverter]::ToUInt32($vec,$k*4)
            ("{0},{1:R},0x{2:X8}" -f $k,$fv,$bits) | Out-File $csv -Append
          }
          $hits.Add([pscustomobject]@{
            label=$label; va=(Hex $va); region=(Hex $rb); protect=('0x{0:X}' -f $m.Protect);
            type=('0x{0:X}' -f $m.Type); csv=[IO.Path]::GetFileName($csv)
          })
        }
        $keep=[Math]::Min($overlap,$combined.Length)
        $carry=New-Object byte[] $keep
        [Array]::Copy($combined,$combined.Length-$keep,$carry,0,$keep)
        $cursor += [UInt64]$n
      }
    }
    $addr=$re
  }
  $hits | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $out "$label.json") -Encoding UTF8
  "${label}_HITS=$($hits.Count)" | Out-File $report -Append
  return $hits
}

try {
  $all=New-Object 'System.Collections.Generic.List[object]'
  foreach ($z in (Scan-C00 'before')) { $all.Add($z) }

  $hwnd=[IntPtr]$xg.MainWindowHandle
  $menu=[XGF]::GetMenu($hwnd)
  $top=New-Object XGF+RECT
  if (-not [XGF]::GetMenuItemRect($hwnd,$menu,4,[ref]$top)) { throw 'Analyze top rect failed' }
  [XGF]::SetForegroundWindow($hwnd) | Out-Null
  ClickXY ([int](($top.Left+$top.Right)/2)) ([int](($top.Top+$top.Bottom)/2))
  Start-Sleep -Milliseconds 250
  $sub=[XGF]::GetSubMenu($menu,4)
  $pos=New-Object XGF+RECT
  if (-not [XGF]::GetMenuItemRect($hwnd,$sub,1,[ref]$pos)) { throw 'Analyze Position rect failed' }
  ClickXY ([int](($pos.Left+$pos.Right)/2)) ([int](($pos.Top+$pos.Bottom)/2))
  'ANALYZE_POSITION_CLICKED=True' | Out-File $report -Append

  foreach ($delay in @(100,1000,4000)) {
    Start-Sleep -Milliseconds $delay
    foreach ($z in (Scan-C00 ("after${delay}ms"))) { $all.Add($z) }
  }
  $all | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $out 'all.json') -Encoding UTF8
  "TOTAL_HITS=$($all.Count)" | Out-File $report -Append
}
finally {
  [void][XGF]::CloseHandle($h)
}
Get-Content $report
