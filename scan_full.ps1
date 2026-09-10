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

Write-Host "`n=== Users subfolders ==="
Get-ChildItem "C:\Users" -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    $uname = $_.Name
    $size = (Get-ChildItem $_.FullName -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    $gb = [math]::Round($size/1GB, 2)
    Write-Host ("  {0,-23} {1,10} GB" -f $uname, $gb)
}

Write-Host "`n=== Large Program Files folders (>500MB) ==="
Get-ChildItem "C:\Program Files" -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    $name = $_.Name
    $size = (Get-ChildItem $_.FullName -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    $gb = [math]::Round($size/1GB, 2)
    if ($gb -gt 0.5) {
        Write-Host ("  {0,-40} {1,8} GB" -f $name, $gb)
    }
}

Write-Host "`n=== Large Program Files (x86) folders (>500MB) ==="
Get-ChildItem "C:\Program Files (x86)" -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    $name = $_.Name
    $size = (Get-ChildItem $_.FullName -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    $gb = [math]::Round($size/1GB, 2)
    if ($gb -gt 0.5) {
        Write-Host ("  {0,-40} {1,8} GB" -f $name, $gb)
    }
}

Write-Host "`n=== Hidden/system files in C:\\ root (>100MB) ==="
Get-ChildItem "C:\" -Force -ErrorAction SilentlyContinue | Where-Object { $_.PSIsContainer -eq $false } | ForEach-Object {
    $sizeMB = [math]::Round($_.Length/1MB, 2)
    if ($sizeMB -gt 100) {
        Write-Host ("  {0,-40} {1,8} MB" -f $_.Name, $sizeMB)
    }
}