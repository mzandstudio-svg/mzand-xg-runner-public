param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][string]$ModelPath,
  [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference='Stop'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$raw=Join-Path $OutDir 'model-decompressed.bin'
$py=@'
import sys,zlib,struct,json
src,out,meta=sys.argv[1:4]
b=zlib.decompress(open(src,'rb').read())
open(out,'wb').write(b)
o=0; rows=[]
for slot in range(4):
    ci,ch,co,f4,bh,bo=struct.unpack_from('<IIIIff',b,o)
    block=24+4*(ci*ch+ch*co+ch+co)
    rows.append(dict(slot=slot,offset=o,input=ci,hidden=ch,output=co,field4=f4,beta_hidden=bh,beta_output=bo,block_bytes=block,
                     header_hex=b[o:o+24].hex(),weights0_hex=b[o+24:o+24+32].hex(),weights1_hex=b[o+24+4096:o+24+4096+32].hex()))
    o+=block
json.dump(rows,open(meta,'w'),indent=2)
print('decompressed_bytes',len(b),'network_end',o,'trailer',len(b)-o)
'@
$pyfile=Join-Path $OutDir 'prep.py'; Set-Content $pyfile $py -Encoding utf8
& python $pyfile $ModelPath $raw (Join-Path $OutDir 'model-layout.json') | Tee-Object -FilePath (Join-Path $OutDir 'prep.txt')

Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class XGMemProbe {
  [StructLayout(LayoutKind.Sequential)] public struct MBI {
    public IntPtr BaseAddress; public IntPtr AllocationBase; public uint AllocationProtect;
    public UIntPtr RegionSize; public uint State; public uint Protect; public uint Type;
  }
  [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool ReadProcessMemory(IntPtr h, IntPtr addr, byte[] buf, int size, out IntPtr read);
  [DllImport("kernel32.dll", SetLastError=true)] static extern int VirtualQueryEx(IntPtr h, IntPtr addr, out MBI mbi, int len);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
  static bool Readable(uint p){ uint x=p & 0xff; return x==0x02||x==0x04||x==0x20||x==0x40||x==0x80; }
  static int Find(byte[] hay,int n,byte[] pat){
    if(pat.Length==0||n<pat.Length)return -1;
    for(int i=0;i<=n-pat.Length;i++){int j=0;for(;j<pat.Length;j++)if(hay[i+j]!=pat[j])break;if(j==pat.Length)return i;}
    return -1;
  }
  public static string Scan(int pid, string rawPath, string outDir){
    byte[] raw=File.ReadAllBytes(rawPath);
    int[] offsets={0,262188,489552,751740};
    var pats=new List<Tuple<string,byte[]>>();
    foreach(int o in offsets){
      int slot=Array.IndexOf(offsets,o);
      byte[] h=new byte[24];Array.Copy(raw,o,h,0,24);pats.Add(Tuple.Create("slot"+slot+"_header",h));
      byte[] p0=new byte[32];Array.Copy(raw,o+24,p0,0,32);pats.Add(Tuple.Create("slot"+slot+"_w0",p0));
      byte[] p1=new byte[32];Array.Copy(raw,o+24+4096,p1,0,32);pats.Add(Tuple.Create("slot"+slot+"_w4096",p1));
    }
    IntPtr hp=OpenProcess(0x0010|0x0400,false,pid); if(hp==IntPtr.Zero) throw new Exception("OpenProcess failed "+Marshal.GetLastWin32Error());
    var sw=new StringWriter(); sw.WriteLine("pid="+pid);
    long addr=0; int mbiSize=Marshal.SizeOf(typeof(MBI)); int regions=0; long bytes=0; int hits=0;
    try{
      while(addr < 0x7fff0000L){
        MBI m; int q=VirtualQueryEx(hp,new IntPtr(addr),out m,mbiSize); if(q==0){addr+=0x1000;continue;}
        long baseAddr=m.BaseAddress.ToInt64(); long size=(long)m.RegionSize.ToUInt64(); if(size<=0){addr+=0x1000;continue;}
        if(m.State==0x1000 && Readable(m.Protect) && (m.Protect & 0x100)==0){
          regions++; bytes+=size;
          long off=0;
          while(off<size){int want=(int)Math.Min(1024*1024,size-off);byte[] buf=new byte[want];IntPtr nr;
            if(ReadProcessMemory(hp,new IntPtr(baseAddr+off),buf,want,out nr) && nr.ToInt64()>0){int got=(int)nr.ToInt64();
              foreach(var p in pats){int from=0;while(from<got){byte[] view=buf;int ix=FindRange(view,from,got,p.Item2);if(ix<0)break;long hit=baseAddr+off+ix;hits++;sw.WriteLine(p.Item1+" hit=0x"+hit.ToString("X8")+" region=0x"+baseAddr.ToString("X8")+" size="+size);
                int before=Math.Min(128,ix);int after=Math.Min(384,got-ix);byte[] dump=new byte[before+after];Array.Copy(buf,ix-before,dump,0,dump.Length);File.WriteAllBytes(Path.Combine(outDir,p.Item1+"_"+hit.ToString("X8")+".bin"),dump);from=ix+p.Item2.Length;}
              }
            } off+=want;
          }
        }
        long next=baseAddr+size; if(next<=addr) next=addr+0x1000; addr=next;
      }
    } finally {CloseHandle(hp);} sw.WriteLine("regions="+regions);sw.WriteLine("readable_bytes="+bytes);sw.WriteLine("hits="+hits);return sw.ToString();
  }
  static int FindRange(byte[] h,int start,int n,byte[] p){for(int i=start;i<=n-p.Length;i++){int j=0;for(;j<p.Length;j++)if(h[i+j]!=p[j])break;if(j==p.Length)return i;}return -1;}
}
"@

$xg=Start-Process $ExePath -WorkingDirectory (Split-Path -Parent $ExePath) -PassThru
Start-Sleep 12
$xg.Refresh(); if($xg.HasExited){throw 'XG exited before memory probe'}
"PID=$($xg.Id)" | Out-File (Join-Path $OutDir 'runtime.txt') -Encoding utf8
"EXE_SHA256=$((Get-FileHash $ExePath -Algorithm SHA256).Hash.ToLowerInvariant())" | Out-File (Join-Path $OutDir 'runtime.txt') -Append
"MODEL_SHA256=$((Get-FileHash $ModelPath -Algorithm SHA256).Hash.ToLowerInvariant())" | Out-File (Join-Path $OutDir 'runtime.txt') -Append
[XGMemProbe]::Scan($xg.Id,$raw,$OutDir) | Out-File (Join-Path $OutDir 'memory-scan.txt') -Encoding utf8
Get-Content (Join-Path $OutDir 'memory-scan.txt')
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
