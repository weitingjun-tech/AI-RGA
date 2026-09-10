$dirs = @('AMD','DrvPath','onetFile','opaivmplayer','PerfLogs','Program Files','Program Files (x86)','SadpLog','sdklog','Users','Windows')
foreach($d in $dirs) {
    $path = "C:\$d"
    try {
        $size = (Get-ChildItem $path -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
        $gb = [math]::Round($size/1GB, 2)
        Write-Host ("{0,-25} {1,10} GB" -f $d, $gb)
    } catch {
        Write-Host ("{0,-25} {1,10}" -f $d, "N/A")
    }
}