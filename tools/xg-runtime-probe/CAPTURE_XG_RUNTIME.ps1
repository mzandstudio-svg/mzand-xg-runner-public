param(
  [string]$ExePath = 'C:\Program Files (x86)\eXtreme Gammon 2\eXtremeGammon2.exe',
  [string]$OutDir = "$PSScriptRoot\out",
  [int]$StartupWaitSeconds = 8,
  [switch]$AttachOnly
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class MemProbe {
  public const uint PROCESS_QUERY_INFORMATION = 0x0400;
  public const uint PROCESS_VM_READ = 0x0010;
  public const uint MEM_COMMIT = 0x1000;

  [StructLayout(LayoutKind.Sequential)]
  public struct MEMORY_BASIC_INFORMATION {
    public IntPtr BaseAddress;
    public IntPtr AllocationBase;
    public uint AllocationProtect;
    public UIntPtr RegionSize;
    public uint State;
    public uint Protect;
    public uint Type;
  }

  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern IntPtr OpenProcess(uint access, bool inheritHandle, int processId);

  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool ReadProcessMemory(
      IntPtr hProcess,
      IntPtr lpBaseAddress,
      byte[] lpBuffer,
      UIntPtr nSize,
      out UIntPtr lpNumberOfBytesRead);

  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern int VirtualQueryEx(
      IntPtr hProcess,
      IntPtr lpAddress,
      out MEMORY_BASIC_INFORMATION lpBuffer,
      uint dwLength);

  [DllImport("kernel32.dll")]
  public static extern bool CloseHandle(IntPtr hObject);
}
"@

function Hex([UInt64]$v) { return ('0x{0:X8}' -f $v) }
function Is-Readable([uint32]$p) {
  if (($p -band 0x100) -ne 0) { return $false }
  if (($p -band 0x01) -ne 0)  { return $false }
  return (($p -band 0x02) -ne 0 -or ($p -band 0x04) -ne 0 -or ($p -band 0x08) -ne 0 -or
          ($p -band 0x10) -ne 0 -or ($p -band 0x20) -ne 0 -or ($p -band 0x40) -ne 0 -or ($p -band 0x80) -ne 0)
}
function Is-Executable([uint32]$p) {
  return (($p -band 0x10) -ne 0 -or ($p -band 0x20) -ne 0 -or ($p -band 0x40) -ne 0 -or ($p -band 0x80) -ne 0)
}

if (-not $AttachOnly) {
  if (-not (Test-Path $ExePath)) { throw "XG executable not found: $ExePath" }
  $existing = Get-Process -Name 'eXtremeGammon2' -ErrorAction SilentlyContinue
  if (-not $existing) {
    Start-Process -FilePath $ExePath | Out-Null
    Start-Sleep -Seconds $StartupWaitSeconds
  }
}

$xg = Get-Process -Name 'eXtremeGammon2' -ErrorAction Stop | Select-Object -First 1
$xg.Refresh()
$pidValue = $xg.Id
$base = [UInt64]$xg.MainModule.BaseAddress.ToInt64()
$size = [UInt64]$xg.MainModule.ModuleMemorySize
$end  = $base + $size

$meta = [ordered]@{
  timestamp_utc = [DateTime]::UtcNow.ToString('o')
  pid = $pidValue
  process = $xg.ProcessName
  exe = $xg.MainModule.FileName
  module_base = Hex $base
  module_size = $size
  module_end = Hex $end
}
$meta | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $OutDir 'process.json') -Encoding UTF8

$xg.Modules | ForEach-Object {
  [pscustomobject]@{
    name = $_.ModuleName
    path = $_.FileName
    base = Hex ([UInt64]$_.BaseAddress.ToInt64())
    size = $_.ModuleMemorySize
  }
} | Export-Csv (Join-Path $OutDir 'modules.csv') -NoTypeInformation -Encoding UTF8

$access = [MemProbe]::PROCESS_QUERY_INFORMATION -bor [MemProbe]::PROCESS_VM_READ
$h = [MemProbe]::OpenProcess($access, $false, $pidValue)
if ($h -eq [IntPtr]::Zero) { throw "OpenProcess failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())" }

try {
  $flatPath = Join-Path $OutDir 'xg-mainmodule-memory.bin'
  $fs = [IO.File]::Open($flatPath, [IO.FileMode]::Create, [IO.FileAccess]::ReadWrite, [IO.FileShare]::Read)
  try {
    $fs.SetLength([Int64]$size)
    $addr = $base
    $rows = New-Object System.Collections.Generic.List[object]
    while ($addr -lt $end) {
      $mbi = New-Object MemProbe+MEMORY_BASIC_INFORMATION
      $q = [MemProbe]::VirtualQueryEx($h, [IntPtr]([Int64]$addr), [ref]$mbi, [uint32][Runtime.InteropServices.Marshal]::SizeOf([type]'MemProbe+MEMORY_BASIC_INFORMATION'))
      if ($q -eq 0) { break }
      $rbase = [UInt64]$mbi.BaseAddress.ToInt64()
      $rsize = [UInt64]$mbi.RegionSize.ToUInt64()
      if ($rsize -eq 0) { break }
      $rend = $rbase + $rsize
      $clipStart = [Math]::Max([double]$rbase, [double]$base)
      $clipEnd   = [Math]::Min([double]$rend,  [double]$end)
      $clipLen   = [UInt64]([Math]::Max(0, $clipEnd - $clipStart))
      $bytesReadTotal = [UInt64]0

      if ($clipLen -gt 0 -and $mbi.State -eq [MemProbe]::MEM_COMMIT -and (Is-Readable $mbi.Protect)) {
        $cursor = [UInt64]$clipStart
        $remaining = $clipLen
        while ($remaining -gt 0) {
          $chunk = [int][Math]::Min([double]$remaining, 1048576.0)
          $buf = New-Object byte[] $chunk
          $got = [UIntPtr]::Zero
          $ok = [MemProbe]::ReadProcessMemory($h, [IntPtr]([Int64]$cursor), $buf, [UIntPtr]([UInt64]$chunk), [ref]$got)
          $n = [UInt64]$got.ToUInt64()
          if ($ok -and $n -gt 0) {
            $fs.Position = [Int64]($cursor - $base)
            $fs.Write($buf, 0, [int]$n)
            $bytesReadTotal += $n
          }
          if ($n -eq 0) { break }
          $cursor += $n
          $remaining -= $n
        }
      }

      $rows.Add([pscustomobject]@{
        base = Hex $rbase
        size = $rsize
        end = Hex $rend
        state = ('0x{0:X}' -f $mbi.State)
        protect = ('0x{0:X}' -f $mbi.Protect)
        type = ('0x{0:X}' -f $mbi.Type)
        executable = (Is-Executable $mbi.Protect)
        readable = (Is-Readable $mbi.Protect)
        bytes_read = $bytesReadTotal
      })
      $addr = $rend
    }
    $rows | Export-Csv (Join-Path $OutDir 'mainmodule-regions.csv') -NoTypeInformation -Encoding UTF8
  }
  finally { $fs.Dispose() }

  $execDir = Join-Path $OutDir 'exec-regions'
  New-Item -ItemType Directory -Force -Path $execDir | Out-Null
  $execRows = New-Object System.Collections.Generic.List[object]
  $addr = [UInt64]0x10000
  $maxAddr = if ([IntPtr]::Size -eq 4) { [UInt64]0x7FFEFFFF } else { [UInt64]0x00007FFFFFFEFFFF }
  $idx = 0
  while ($addr -lt $maxAddr) {
    $mbi = New-Object MemProbe+MEMORY_BASIC_INFORMATION
    $q = [MemProbe]::VirtualQueryEx($h, [IntPtr]([Int64]$addr), [ref]$mbi, [uint32][Runtime.InteropServices.Marshal]::SizeOf([type]'MemProbe+MEMORY_BASIC_INFORMATION'))
    if ($q -eq 0) { break }
    $rbase = [UInt64]$mbi.BaseAddress.ToInt64()
    $rsize = [UInt64]$mbi.RegionSize.ToUInt64()
    if ($rsize -eq 0) { break }
    $rend = $rbase + $rsize

    if ($mbi.State -eq [MemProbe]::MEM_COMMIT -and (Is-Executable $mbi.Protect) -and (Is-Readable $mbi.Protect) -and $rsize -le 67108864) {
      $name = ('exec_{0:D4}_{1:X8}_{2:X}.bin' -f $idx, $rbase, $rsize)
      $path = Join-Path $execDir $name
      $ofs = [IO.File]::Open($path, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::Read)
      $total = [UInt64]0
      try {
        $cursor = $rbase
        $remaining = $rsize
        while ($remaining -gt 0) {
          $chunk = [int][Math]::Min([double]$remaining, 1048576.0)
          $buf = New-Object byte[] $chunk
          $got = [UIntPtr]::Zero
          $ok = [MemProbe]::ReadProcessMemory($h, [IntPtr]([Int64]$cursor), $buf, [UIntPtr]([UInt64]$chunk), [ref]$got)
          $n = [UInt64]$got.ToUInt64()
          if (-not $ok -or $n -eq 0) { break }
          $ofs.Write($buf, 0, [int]$n)
          $total += $n
          $cursor += $n
          $remaining -= $n
        }
      } finally { $ofs.Dispose() }
      if ($total -eq 0) { Remove-Item $path -Force -ErrorAction SilentlyContinue }
      $execRows.Add([pscustomobject]@{
        index=$idx; base=Hex $rbase; size=$rsize; end=Hex $rend;
        protect=('0x{0:X}' -f $mbi.Protect); type=('0x{0:X}' -f $mbi.Type);
        bytes_read=$total; file=if($total-gt0){$name}else{''}
      })
      $idx++
    }
    $addr = $rend
  }
  $execRows | Export-Csv (Join-Path $OutDir 'exec-regions.csv') -NoTypeInformation -Encoding UTF8
}
finally {
  [void][MemProbe]::CloseHandle($h)
}

Get-FileHash (Join-Path $OutDir 'xg-mainmodule-memory.bin') -Algorithm SHA256 |
  Select-Object Algorithm,Hash,Path |
  Format-List | Out-String | Set-Content (Join-Path $OutDir 'SHA256.txt') -Encoding UTF8

Write-Host "CAPTURE_COMPLETE=$OutDir"
Get-ChildItem $OutDir -Recurse | Select-Object FullName,Length | Format-Table -AutoSize
