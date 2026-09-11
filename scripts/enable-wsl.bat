@echo off
REM 启用 WSL2 所需的 Windows 功能
REM
REM 用法：右键本文件 -> 以管理员身份运行
REM 本脚本不会自动重启，重启时机由你自己决定。
REM
REM 为什么用 dism 而不是 wsl --install：
REM   wsl --install 是个黑盒，它自行决定装什么、要不要重启，报错也不明确。
REM   dism 直接可控，/norestart 保证不会在我们没准备好时把机器重启掉。
REM
REM 【重要】本文件必须保存为 GBK 编码。
REM   cmd.exe 按系统 ANSI 代码页读取 .bat，中文 Windows 下是 GBK。
REM   若存成 UTF-8，中文会被解码成乱码，进而破坏批处理语法结构。

set LOG=D:\mydo\wsl-enable.log

echo === 开始 %DATE% %TIME% === > "%LOG%"

REM 确认管理员权限：net session 需要管理员才能成功
net session >nul 2>&1
if errorlevel 1 (
    echo 错误：未以管理员身份运行，无法启用系统功能。 >> "%LOG%"
    echo.
    echo [失败] 未获得管理员权限。
    echo 请右键本文件，选择「以管理员身份运行」。
    pause
    exit /b 1
)
echo 管理员权限：已确认 >> "%LOG%"

REM 两个功能缺一不可：
REM   Microsoft-Windows-Subsystem-Linux = WSL 本体
REM   VirtualMachinePlatform            = WSL2 依赖的轻量虚拟机平台
REM                                       （家庭版没有 Hyper-V，WSL2 只能靠它）
for %%F in (Microsoft-Windows-Subsystem-Linux VirtualMachinePlatform) do (
    echo. >> "%LOG%"
    echo --- 启用 %%F --- >> "%LOG%"
    dism.exe /online /enable-feature /featurename:%%F /all /norestart >> "%LOG%" 2>&1
    echo 退出码: %ERRORLEVEL% >> "%LOG%"
)

echo. >> "%LOG%"
echo --- 当前功能状态 --- >> "%LOG%"
dism.exe /online /get-featureinfo /featurename:Microsoft-Windows-Subsystem-Linux | findstr /C:"State" >> "%LOG%" 2>&1
dism.exe /online /get-featureinfo /featurename:VirtualMachinePlatform | findstr /C:"State" >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo === 完成 %DATE% %TIME% === >> "%LOG%"
echo 注意：功能启用后需要重启电脑才能生效。 >> "%LOG%"

echo.
echo [完成] 结果已写入 %LOG%
echo 注意：需要重启电脑后 WSL2 才能生效。
pause
