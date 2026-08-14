$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class XGMemV2 {
  public const uint PROCESS_QUERY_INFORMATION=0x0400;
  public const uint PROCESS_VM_READ=0x0010;
  public const uint MEM_COMMIT=0x1000;
  [StructLayout(LayoutKind.Sequential)] public struct MBI {
    public IntPtr BaseAddress; public IntPtr AllocationBase; public uint AllocationProtect;
    public UIntPtr RegionSize; public uint State; public uint Protect; public uint Type;
  }
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
  [DllImport("kernel32.dll",SetLastError=true)] public static extern IntPtr OpenProcess(uint a,bool i,int pid);
  [DllImport("kernel32.dll",SetLastError=true)] public static extern bool ReadProcessMemory(IntPtr h,IntPtr a,byte[] b,UIntPtr n,out UIntPtr got);
  [DllImport("kernel32.dll",SetLastError=true)] public static extern int VirtualQueryEx(IntPtr h,IntPtr a,out MBI m,uint n);
  [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr hMenu,int nPos);
  [DllImport("user32.dll")] public static extern bool GetMenuItemRect(IntPtr hWnd,IntPtr hMenu,uint uItem,out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
}
"@

function IsReadable([uint32]$p){
  if(($p-band 0x100)-ne0 -or ($p-band 1)-ne0){return $false}
  return (($p-band 2)-ne0 -or ($p-band 4)-ne0 -or ($p-band 8)-ne0 -or ($p-band 0x10)-ne0 -or ($p-band 0x20)-ne0 -or ($p-band 0x40)-ne0 -or ($p-band 0x80)-ne0)
}
function Hex([UInt64]$x){'0x{0:X8}'-f$x}
function ClickXY([int]$x,[int]$y){[XGMemV2]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 80;[XGMemV2]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 50;[XGMemV2]::mouse_event(4,0,0,0,[UIntPtr]::Zero)}

# Exact historical/GNU-compatible first 200 float32 inputs for the standard start board (C00).
$pattern=[Convert]::FromBase64String('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgD8AAIA/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIA/AACAPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIA/AACAPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgD8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAPwAAgD8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgD8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=')
if($pattern.Length-ne800){throw "pattern length $($pattern.Length)"}

$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$xg.Refresh()
if($xg.MainWindowTitle-notlike'*Position.xgp*'){throw "Expected Position.xgp, got [$($xg.MainWindowTitle)]"}
$out="$env:GITHUB_WORKSPACE\xg-input-probe-v2"
New-Item -ItemType Directory -Force -Path $out|Out-Null
$report=Join-Path $out 'report.txt'
"PID=$($xg.Id)"|Out-File $report
"TITLE=$($xg.MainWindowTitle)"|Out-File $report -Append
"PATTERN_BYTES=$($pattern.Length)"|Out-File $report -Append

$h=[XGMemV2]::OpenProcess(([XGMemV2]::PROCESS_QUERY_INFORMATION-bor[XGMemV2]::PROCESS_VM_READ),$false,$xg.Id)
if($h-eq[IntPtr]::Zero){throw 'OpenProcess failed'}

function FindPattern([string]$label){
  $hits=New-Object 'System.Collections.Generic.List[object]'
  $addr=[UInt64]0x10000
  $max=[UInt64]0x7FFEFFFF
  while($addr-lt$max){
    $m=New-Object XGMemV2+MBI
    $q=[XGMemV2]::VirtualQueryEx($h,[IntPtr]([Int64]$addr),[ref]$m,[uint32][Runtime.InteropServices.Marshal]::SizeOf([type]'XGMemV2+MBI'))
    if($q-eq0){break}
    $rb=[UInt64]$m.BaseAddress.ToInt64();$rs=[UInt64]$m.RegionSize.ToUInt64();if($rs-eq0){break};$re=$rb+$rs
    if($m.State-eq[XGMemV2]::MEM_COMMIT -and (IsReadable $m.Protect) -and $rs-ge[UInt64]$pattern.Length -and $rs-le[UInt64]134217728){
      $chunkMax=4MB;$overlap=$pattern.Length-1;$cursor=$rb;$carry=New-Object byte[] 0
      while($cursor-lt$re){
        $want=[int][Math]::Min([double]$chunkMax,[double]($re-$cursor))
        $buf=New-Object byte[] $want;$got=[UIntPtr]::Zero
        $ok=[XGMemV2]::ReadProcessMemory($h,[IntPtr]([Int64]$cursor),$buf,[UIntPtr]([UInt64]$want),[ref]$got)
        $n=[int]$got.ToUInt64();if(-not$ok-or$n-le0){break}
        if($n-ne$buf.Length){$tmp=New-Object byte[] $n;[Array]::Copy($buf,$tmp,$n);$buf=$tmp}
        $combined=New-Object byte[] ($carry.Length+$buf.Length);if($carry.Length){[Array]::Copy($carry,0,$combined,0,$carry.Length)};[Array]::Copy($buf,0,$combined,$carry.Length,$buf.Length)
        $limit=$combined.Length-$pattern.Length
        for($i=0;$i-le$limit;$i+=4){
          if($combined[$i]-ne$pattern[0]){continue}
          $same=$true
          for($j=4;$j-lt$pattern.Length;$j+=4){if($combined[$i+$j]-ne$pattern[$j] -or $combined[$i+$j+1]-ne$pattern[$j+1] -or $combined[$i+$j+2]-ne$pattern[$j+2] -or $combined[$i+$j+3]-ne$pattern[$j+3]){$same=$false;break}}
          if($same){
            $va=[UInt64]([Int64]$cursor-[Int64]$carry.Length+$i)
            $vec=New-Object byte[] (252*4);$got2=[UIntPtr]::Zero
            [void][XGMemV2]::ReadProcessMemory($h,[IntPtr]([Int64]$va),$vec,[UIntPtr]([UInt64]$vec.Length),[ref]$got2)
            $csv=Join-Path $out ("{0}-hit-{1:X8}.csv"-f$label,$va)
            'index,value,bits'|Out-File $csv
            for($k=0;$k-lt252;$k++){if(($k*4+4)-gt$got2.ToUInt64()){break};$f=[BitConverter]::ToSingle($vec,$k*4);$bits=[BitConverter]::ToUInt32($vec,$k*4);("{0},{1:R},0x{2:X8}"-f$k,$f,$bits)|Out-File $csv -Append}
            $hits.Add([pscustomobject]@{label=$label;va=(Hex $va);region=(Hex $rb);protect=('0x{0:X}'-f$m.Protect);type=('0x{0:X}'-f$m.Type);csv=[IO.Path]::GetFileName($csv)})
          }
        }
        $keep=[Math]::Min($overlap,$combined.Length);$carry=New-Object byte[] $keep;[Array]::Copy($combined,$combined.Length-$keep,$carry,0,$keep)
        $cursor+=[UInt64]$n
      }
    }
    $addr=$re
  }
  $hits|ConvertTo-Json -Depth 4|Set-Content (Join-Path $out "$label-hits.json") -Encoding UTF8
  "${label}_HITS=$($hits.Count)"|Out-File $report -Append
  return $hits
}

try{
  $all=New-Object 'System.Collections.Generic.List[object]'
  foreach($z in (FindPattern 'before')){$all.Add($z)}

  $hwnd=[IntPtr]$xg.MainWindowHandle;$menu=[XGMemV2]::GetMenu($hwnd);$top=New-Object XGMemV2+RECT
  if(-not[XGMemV2]::GetMenuItemRect($hwnd,$menu,4,[ref]$top)){throw 'Analyze top rect failed'}
  [XGMemV2]::SetForegroundWindow($hwnd)|Out-Null;Start-Sleep -Milliseconds 150
  ClickXY ([int](($top.Left+$top.Right)/2)) ([int](($top.Top+$top.Bottom)/2));Start-Sleep -Milliseconds 250
  $sub=[XGMemV2]::GetSubMenu($menu,4);$pos=New-Object XGMemV2+RECT
  if(-not[XGMemV2]::GetMenuItemRect($hwnd,$sub,1,[ref]$pos)){throw 'Analyze Position row rect failed'}
  ClickXY ([int](($pos.Left+$pos.Right)/2)) ([int](($pos.Top+$pos.Bottom)/2))
  'ANALYZE_POSITION_CLICKED=True'|Out-File $report -Append

  foreach($delay in @(50,200,750,2000,5000)){
    Start-Sleep -Milliseconds $delay
    foreach($z in (FindPattern ("after${delay}ms"))){$all.Add($z)}
  }
  $all|ConvertTo-Json -Depth 5|Set-Content (Join-Path $out 'all-hits.json') -Encoding UTF8
  "TOTAL_HITS=$($all.Count)"|Out-File $report -Append
}
finally{[void][XGMemV2]::CloseHandle($h)}
Get-Content $report
