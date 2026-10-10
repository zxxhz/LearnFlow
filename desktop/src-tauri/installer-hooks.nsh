; LearnFlow NSIS 安装/卸载钩子（tauri.conf.json → bundle.windows.nsis.installerHooks 引用）
; 背景：桌面壳退出后后端子进程 learnflow-backend.exe 可能残留（孤儿进程），
; 它会锁住 backend\_internal 下的文件（如 PIL 的 .pyd），导致覆盖安装失败。
; 因此在安装/卸载动作前预杀 LearnFlow 相关进程；进程不存在时 taskkill 报错无害，忽略即可。

!macro NSIS_HOOK_PREINSTALL
  nsExec::Exec 'taskkill /F /T /IM learnflow-desktop.exe'
  Pop $0
  nsExec::Exec 'taskkill /F /T /IM LearnFlow.exe'
  Pop $0
  nsExec::Exec 'taskkill /F /T /IM learnflow-backend.exe'
  Pop $0
  Sleep 500
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; 清理旧版本可能残留的 matplotlib 示例图片与工具栏图标，防止出现在用户的 Windows 图片/照片中
  RMDir /r "$INSTDIR\backend\_internal\matplotlib\mpl-data\sample_data"
  RMDir /r "$INSTDIR\backend\_internal\matplotlib\mpl-data\images"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  nsExec::Exec 'taskkill /F /T /IM learnflow-desktop.exe'
  Pop $0
  nsExec::Exec 'taskkill /F /T /IM LearnFlow.exe'
  Pop $0
  nsExec::Exec 'taskkill /F /T /IM learnflow-backend.exe'
  Pop $0
  Sleep 500
!macroend
