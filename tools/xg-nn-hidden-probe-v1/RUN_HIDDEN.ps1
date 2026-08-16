param(
 [Parameter(Mandatory=$true)][string]$ExePath,
 [Parameter(Mandatory=$true)][string]$ModelPath,
 [Parameter(Mandatory=$true)][string]$CasesPath,
 [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference='Stop'
$workspace=$env:GITHUB_WORKSPACE
$py=Get-Content (Join-Path $workspace 'tools\xg-nn-allnet-input-v1\decode_allnet.py') -Raw
$needle=@'
                    outvals=[]
                    ob=read(p_out,co*4)
                    if len(ob)==co*4: outvals=list(struct.unpack('<%df'%co,ob))
                    fn=f"{net['label']}_{obj:08x}_input{ci}.txt"
'@
$replacement=@'
                    outvals=[]
                    ob=read(p_out,co*4)
                    if len(ob)==co*4: outvals=list(struct.unpack('<%df'%co,ob))
                    hidden_pre=[]; hidden_act=[]
                    hb=read(p_hidden_pre,ch*4)
                    if len(hb)==ch*4: hidden_pre=list(struct.unpack('<%df'%ch,hb))
                    ab=read(p_hidden_act,ch*4)
                    if len(ab)==ch*4: hidden_act=list(struct.unpack('<%df'%ch,ab))
                    fn=f"{net['label']}_{obj:08x}_input{ci}.txt"
                    if hidden_pre:
                        with open(os.path.join(out,f"{net['label']}_{obj:08x}_hidden_pre.txt"),'w') as z:
                            for ii,v in enumerate(hidden_pre): z.write(f'{ii} {v:.17g}\n')
                    if hidden_act:
                        with open(os.path.join(out,f"{net['label']}_{obj:08x}_hidden_act.txt"),'w') as z:
                            for ii,v in enumerate(hidden_act): z.write(f'{ii} {v:.17g}\n')
'@
if(-not $py.Contains($needle)){throw 'decode_allnet hidden anchor missing'}
$py=$py.Replace($needle,$replacement)
$needle2="                    records.append(rec)"
$replacement2=@'
                    rec['hidden_pre_values']=hidden_pre
                    rec['hidden_act_values']=hidden_act
                    records.append(rec)
'@
if(-not $py.Contains($needle2)){throw 'decode_allnet record anchor missing'}
$py=$py.Replace($needle2,$replacement2)
$tempPy=Join-Path $env:RUNNER_TEMP 'decode_allnet_hidden.py'; Set-Content $tempPy $py -Encoding utf8
$runner=Get-Content (Join-Path $workspace 'tools\xg-nn-allnet-input-v1\RUN_ALLNET.ps1') -Raw
$old="`$env:MZ_ALLNET_SCRIPT=(Join-Path `$workspace 'tools\xg-nn-allnet-input-v1\decode_allnet.py')"
$new="`$env:MZ_ALLNET_SCRIPT='$($tempPy.Replace("'","''"))'"
if(-not $runner.Contains($old)){throw 'RUN_ALLNET script anchor missing'}
$runner=$runner.Replace($old,$new)
$tempRun=Join-Path $env:RUNNER_TEMP 'RUN_ALLNET_HIDDEN.ps1'; Set-Content $tempRun $runner -Encoding utf8
& $tempRun -ExePath $ExePath -ModelPath $ModelPath -CasesPath $CasesPath -OutDir $OutDir
