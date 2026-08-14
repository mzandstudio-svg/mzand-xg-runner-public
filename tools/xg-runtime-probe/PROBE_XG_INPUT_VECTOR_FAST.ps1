$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class XGF {
 public const uint PROCESS_QUERY_INFORMATION=0x0400, PROCESS_VM_READ=0x0010, MEM_COMMIT=0x1000;
 [StructLayout(LayoutKind.Sequential)] public struct MBI { public IntPtr BaseAddress,AllocationBase; public uint AllocationProtect; public UIntPtr RegionSize; public uint State,Protect,Type; }
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
 public static int[] Search4(byte[] h,byte[] n) {
   var a=new List<int>(); if(n.Length==0||h.Length<n.Length)return a.ToArray();
   int anchor=91; byte av=n[anchor]; int lim=h.Length-n.Length;
   for(int i=0;i<=lim;i+=4){ if(h[i+anchor]!=av)continue; bool ok=true; for(int j=0;j<n.Length;j++){if(h[i+j]!=n[j]){ok=false;break;}} if(ok)a.Add(i); }
   return a.ToArray();
 }
}
"@
function Readable([uint32]$p){if(($p-band0x100)-ne0-or($p-band1)-ne0){return$false};return(($p-band2)-ne0-or($p-band4)-ne0-or($p-band8)-ne0-or($p-band0x10)-ne0-or($p-band0x20)-ne0-or($p-band0x40)-ne0-or($p-band0x80)-ne0)}
function H([UInt64]$x){'0x{0:X8}'-f$x}
function Click([int]$x,[int]$y){[XGF]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 60;[XGF]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 40;[XGF]::mouse_event(4,0,0,0,[UIntPtr]::Zero)}
$pattern=[Convert]::FromBase64String('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgD8AAIA/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIA/AACAPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIA/AACAPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgD8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAPwAAgD8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgD8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=')
$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1;$xg.Refresh();if($xg.MainWindowTitle-notlike'*Position.xgp*'){throw "Position not ready: $($xg.MainWindowTitle)"}
$out="$env:GITHUB_WORKSPACE\xg-input-probe-v3";New-Item -ItemType Directory -Force $out|Out-Null;$rep="$out\report.txt";"TITLE=$($xg.MainWindowTitle)"|Out-File $rep
$h=[XGF]::OpenProcess(([XGF]::PROCESS_QUERY_INFORMATION-bor[XGF]::PROCESS_VM_READ),$false,$xg.Id);if($h-eq[IntPtr]::Zero){throw'OpenProcess'}
function Scan([string]$lab){
 $hits=New-Object System.Collections.Generic.List[object];$addr=[UInt64]0x10000;$max=[UInt64]0x7FFEFFFF;$over=$pattern.Length-1
 while($addr-lt$max){$m=New-Object XGF+MBI;$q=[XGF]::VirtualQueryEx($h,[IntPtr]([Int64]$addr),[ref]$m,[uint32][Runtime.InteropServices.Marshal]::SizeOf([type]'XGF+MBI'));if($q-eq0){break};$rb=[UInt64]$m.BaseAddress.ToInt64();$rs=[UInt64]$m.RegionSize.ToUInt64();if($rs-eq0){break};$re=$rb+$rs
  if($m.State-eq[XGF]::MEM_COMMIT-and(Readable $m.Protect)-and$rs-ge800-and$rs-le268435456){$cur=$rb;$carry=New-Object byte[] 0
   while($cur-lt$re){$want=[int][Math]::Min(8388608,[double]($re-$cur));$buf=New-Object byte[] $want;$got=[UIntPtr]::Zero;$ok=[XGF]::ReadProcessMemory($h,[IntPtr]([Int64]$cur),$buf,[UIntPtr]([UInt64]$want),[ref]$got);$n=[int]$got.ToUInt64();if(-not$ok-or$n-le0){break};if($n-ne$buf.Length){$b2=New-Object byte[]$n;[Array]::Copy($buf,$b2,$n);$buf=$b2};$comb=New-Object byte[]($carry.Length+$buf.Length);if($carry.Length){[Array]::Copy($carry,$comb,$carry.Length)};[Array]::Copy($buf,0,$comb,$carry.Length,$buf.Length)
    foreach($i in [XGF]::Search4($comb,$pattern)){$va=[UInt64]([Int64]$cur-$carry.Length+$i);$vec=New-Object byte[](252*4);$g2=[UIntPtr]::Zero;[void][XGF]::ReadProcessMemory($h,[IntPtr]([Int64]$va),$vec,[UIntPtr]([UInt64]$vec.Length),[ref]$g2);$csv="$out\$lab-$('{0:X8}'-f$va).csv";'index,value,bits'|Out-File$csv;for($k=0;$k-lt252-and($k*4+4)-le$g2.ToUInt64();$k++){('{0},{1:R},0x{2:X8}'-f$k,[BitConverter]::ToSingle($vec,$k*4),[BitConverter]::ToUInt32($vec,$k*4))|Out-File$csv -Append};$hits.Add([pscustomobject]@{label=$lab;va=(H$va);protect=('0x{0:X}'-f$m.Protect);type=('0x{0:X}'-f$m.Type);csv=[IO.Path]::GetFileName($csv)})}
    $keep=[Math]::Min($over,$comb.Length);$carry=New-Object byte[]$keep;[Array]::Copy($comb,$comb.Length-$keep,$carry,0,$keep);$cur+=[UInt64]$n
   }
  };$addr=$re
 };$hits|ConvertTo-Json -Depth4|Set-Content "$out\$lab.json";"${lab}_HITS=$($hits.Count)"|Out-File$rep -Append;return$hits
}
try{$all=New-Object System.Collections.Generic.List[object];foreach($z in(Scan'before')){$all.Add($z)}
 $hw=[IntPtr]$xg.MainWindowHandle;$mn=[XGF]::GetMenu($hw);$r=New-Object XGF+RECT;if(-not[XGF]::GetMenuItemRect($hw,$mn,4,[ref]$r)){throw'Analyze rect'};[XGF]::SetForegroundWindow($hw)|Out-Null;Click ([int](($r.Left+$r.Right)/2)) ([int](($r.Top+$r.Bottom)/2));Start-Sleep -Milliseconds250;$sm=[XGF]::GetSubMenu($mn,4);$p=New-Object XGF+RECT;if(-not[XGF]::GetMenuItemRect($hw,$sm,1,[ref]$p)){throw'Position rect'};Click ([int](($p.Left+$p.Right)/2)) ([int](($p.Top+$p.Bottom)/2));'ANALYZE_POSITION_CLICKED=True'|Out-File$rep -Append
 foreach($d in@(100,1000,4000)){Start-Sleep -Milliseconds$d;foreach($z in(Scan("after${d}ms"))){$all.Add($z)}};$all|ConvertTo-Json -Depth5|Set-Content "$out\all.json";"TOTAL_HITS=$($all.Count)"|Out-File$rep -Append
}finally{[void][XGF]::CloseHandle($h)};Get-Content$rep
