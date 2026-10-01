#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! LearnFlow 桌面壳（PRD §5.9 / §7.1）：
//! 启动时拉起本地后端，就绪后加载 127.0.0.1:8420；
//! 托盘常驻（显示窗口 / 开机自启 / 退出），关窗最小化到托盘，退出时回收后端进程。
//! 打包版（release）：拉起随包分发的 PyInstaller 后端（resources/backend/）；
//! 开发版（debug）：uv run python -m app.main（需已安装 uv）。

use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

use tauri::menu::{CheckMenuItem, Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_autostart::{ManagerExt, MacosLauncher};

struct Backend(Mutex<Option<Child>>);

fn port() -> u16 {
    std::env::var("LEARNFLOW_PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(8420)
}

fn backend_dir() -> PathBuf {
    if let Ok(p) = std::env::var("LEARNFLOW_BACKEND_DIR") {
        return PathBuf::from(p);
    }
    // 从 exe 向上找包含 backend/app 的目录（开发期 target/debug 在项目深处）
    if let Ok(exe) = std::env::current_exe() {
        let mut dir = exe.parent().map(|p| p.to_path_buf());
        while let Some(d) = dir {
            if d.join("backend").join("app").exists() {
                return d.join("backend");
            }
            dir = d.parent().map(|p| p.to_path_buf());
        }
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")).join("backend")
}

fn backend_ready(port: u16) -> bool {
    TcpStream::connect(("127.0.0.1", port)).is_ok()
}

fn packaged_backend_exe(app: &AppHandle) -> Option<PathBuf> {
    let exe = app
        .path()
        .resource_dir()
        .ok()?
        .join("backend")
        .join("learnflow-backend.exe");
    if exe.exists() {
        Some(exe)
    } else {
        eprintln!("[learnflow] 未找到内置后端：{}", exe.display());
        None
    }
}

fn spawn_backend(app: &AppHandle, port: u16) -> Option<Child> {
    // 打包版拉起 PyInstaller 后端（exe 同目录为只读安装区，数据走系统应用数据目录）；
    // LEARNFLOW_BACKEND_EXE 可在开发期显式指定打包后端联调。
    let backend: Option<PathBuf> = if let Ok(p) = std::env::var("LEARNFLOW_BACKEND_EXE") {
        Some(PathBuf::from(p))
    } else if cfg!(debug_assertions) {
        None
    } else {
        packaged_backend_exe(app)
    };

    let mut cmd = match backend {
        Some(exe) => {
            let mut c = Command::new(&exe);
            if let Some(dir) = exe.parent() {
                c.current_dir(dir);
            }
            if let Ok(data) = app.path().app_data_dir() {
                let _ = std::fs::create_dir_all(&data);
                c.env("APP_DATA_DIR", &data);
            }
            c
        }
        None => {
            let mut c = Command::new("uv");
            c.args(["run", "python", "-m", "app.main"])
                .current_dir(backend_dir());
            c
        }
    };
    cmd.env("APP_OPEN_BROWSER", "0")
        .env("APP_PORT", port.to_string());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW：不弹控制台
    }
    match cmd.spawn() {
        Ok(child) => Some(child),
        Err(e) => {
            eprintln!("[learnflow] 后端进程启动失败（打包版应含内置后端，开发版需已安装 uv）: {e}");
            None
        }
    }
}

fn main() {
    let port = port();

    tauri::Builder::default()
        // 单实例（须最先注册）：二次启动立即退出并唤起主实例窗口——后端只应有一个
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_main(app);
        }))
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec![]),
        ))
        .manage(Backend(Mutex::new(None)))
        .setup(move |app| {
            let handle = app.handle().clone();

            // ---- 托盘菜单：显示窗口 / 开机自启 / 退出 ----
            let autostart_on = handle.autolaunch().is_enabled().unwrap_or(false);
            let show = MenuItem::with_id(app, "show", "显示窗口", true, None::<&str>)?;
            let autostart = CheckMenuItem::with_id(
                app, "autostart", "开机自启", true, autostart_on, None::<&str>,
            )?;
            let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &autostart, &quit])?;

            let autostart_item = autostart.clone();
            TrayIconBuilder::with_id("main-tray")
                .icon(app.default_window_icon().expect("missing icon").clone())
                .tooltip("LearnFlow · 学习 Agent")
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(move |app, event| match event.id().as_ref() {
                    "show" => show_main(app),
                    "quit" => app.exit(0),
                    "autostart" => {
                        let al = app.autolaunch();
                        let now_on = if al.is_enabled().unwrap_or(false) {
                            let _ = al.disable();
                            false
                        } else {
                            let _ = al.enable();
                            true
                        };
                        let _ = autostart_item.set_checked(now_on);
                    }
                    _ => {}
                })
                .build(app)?;

            // ---- 后端就绪等待（独立线程，避免阻塞 setup） ----
            // 主窗口由 tauri.conf.json 定义（label=main，加载 start.html 启动页）
            std::thread::spawn(move || {
                let mut spawned = false;
                if !backend_ready(port) {
                    let child = spawn_backend(&handle, port);
                    *handle.state::<Backend>().0.lock().unwrap() = child;
                    spawned = true;
                }
                let mut ready = backend_ready(port);
                for _ in 0..100 {
                    if ready {
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(600));
                    ready = backend_ready(port);
                }
                if let Some(win) = handle.get_webview_window("main") {
                    if ready {
                        let _ = win.eval(&format!(
                            "location.replace('http://127.0.0.1:{port}/')"
                        ));
                    } else {
                        let _ = win.eval(
                            "document.getElementById('msg').style.display='none';\
                             document.querySelector('.spin')?.remove();\
                             document.getElementById('err').style.display='block';",
                        );
                    }
                }
                if !spawned {
                    // 已有外部后端在跑，清空占位避免误杀
                    *handle.state::<Backend>().0.lock().unwrap() = None;
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            // 关窗 → 隐藏到托盘（退出请走托盘菜单）
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(mut child) = app.state::<Backend>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}

fn show_main(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.unminimize();
        let _ = win.set_focus();
    }
}
