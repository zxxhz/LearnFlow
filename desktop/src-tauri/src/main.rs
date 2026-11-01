#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! LearnFlow 桌面壳（PRD §5.9 / §7.1）：
//! 启动时拉起本地后端，就绪后加载 127.0.0.1:8420；
//! 托盘常驻（显示窗口 / 退出），关窗最小化到托盘，退出时回收后端进程树。
//! 打包版（release）：拉起随包分发的 PyInstaller 后端（resources/backend/）；
//! 开发版（debug）：uv run python -m app.main（需已安装 uv）。

use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
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
    // TCP 可连只说明端口被占用；必须验证是 LearnFlow 后端：HTTP /api/system/access-info 返回 200
    // 且响应体是含 "port" 或 "lan_mode" 字段的 JSON——防止同端口的无关 SPA/静态服务
    // 用 200 空页把壳骗进别人的页面。回环来源免令牌（_AccessGuard）。
    let Ok(mut s) = TcpStream::connect(("127.0.0.1", port)) else {
        return false;
    };
    let _ = s.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = s.set_write_timeout(Some(Duration::from_secs(2)));
    if s.write_all(b"GET /api/system/access-info HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    // HTTP/1.0 + Connection: close：读到对端关闭即完整响应；设上限防恶意服务灌数据
    let mut raw = Vec::new();
    let mut chunk = [0u8; 4096];
    loop {
        match s.read(&mut chunk) {
            Ok(0) => break,
            Ok(n) => {
                raw.extend_from_slice(&chunk[..n]);
                if raw.len() > 64 * 1024 {
                    return false;
                }
            }
            Err(_) => break,
        }
    }
    let text = String::from_utf8_lossy(&raw);
    if !text.starts_with("HTTP/") || !text.contains(" 200 ") {
        return false;
    }
    // 头与体以空行分隔；无体或解析不出 JSON 对象均视为未就绪
    let Some(body) = text.split_once("\r\n\r\n").map(|(_, b)| b) else {
        return false;
    };
    let Ok(v) = serde_json::from_str::<serde_json::Value>(body.trim()) else {
        return false;
    };
    v.get("port").is_some() || v.get("lan_mode").is_some()
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

/// 打包版后端日志文件：`<app_data_dir>/logs/backend.log`（追加写）。
/// 超过 5MB 先轮转为 backend.log.1（覆盖旧 .1，仅保留一份历史）。
/// 目录/文件打开失败返回 None，调用方降级 Stdio::null()——日志不能影响后端启动。
fn open_backend_log(app_data: &PathBuf) -> Option<std::fs::File> {
    const MAX_LOG_BYTES: u64 = 5 * 1024 * 1024;
    let logs_dir = app_data.join("logs");
    std::fs::create_dir_all(&logs_dir).ok()?;
    let log = logs_dir.join("backend.log");
    if let Ok(meta) = std::fs::metadata(&log) {
        if meta.len() > MAX_LOG_BYTES {
            let _ = std::fs::rename(&log, logs_dir.join("backend.log.1"));
        }
    }
    std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log)
        .ok()
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
                // 打包版无控制台可看：stdout/stderr 追加重定向到 logs/backend.log，
                // 便于排查发布版后端崩溃；打不开日志则丢弃输出，照常启动
                match open_backend_log(&data) {
                    Some(f) => {
                        let stderr_f = f.try_clone().ok();
                        c.stdout(Stdio::from(f));
                        c.stderr(match stderr_f {
                            Some(sf) => Stdio::from(sf),
                            None => Stdio::null(),
                        });
                    }
                    None => {
                        c.stdout(Stdio::null());
                        c.stderr(Stdio::null());
                    }
                }
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
        // 每日复习提醒的系统通知（前端经 @tauri-apps/plugin-notification 调用）
        .plugin(tauri_plugin_notification::init())
        // 应用内自动更新（前端经 @tauri-apps/plugin-updater 检查/下载/安装，
        // 端点指向 GitHub Releases 的 latest.json，签名见 tauri.conf.json plugins.updater）
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .manage(Backend(Mutex::new(None)))
        .setup(move |app| {
            let handle = app.handle().clone();

            // 启动时确保禁用开机自启（不再提供自启功能，清理历史残留注册表）
            let _ = handle.autolaunch().disable();

            // ---- 托盘菜单：显示窗口 / 退出 ----
            let show = MenuItem::with_id(app, "show", "显示窗口", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;

            TrayIconBuilder::with_id("main-tray")
                .icon(app.default_window_icon().expect("missing icon").clone())
                .tooltip("LearnFlow · 学习 Agent")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_tray_icon_event(|tray, event| match event {
                    TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    }
                    | TrayIconEvent::DoubleClick {
                        button: MouseButton::Left,
                        ..
                    } => {
                        let app = tray.app_handle();
                        show_main(app);
                    }
                    _ => {}
                })
                .on_menu_event(move |app, event| match event.id().as_ref() {
                    "show" => show_main(app),
                    "quit" => app.exit(0),
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
                    // 后端进程已闪退（如缺依赖）时提前报错，不必等满 60s
                    if spawned {
                        let died = {
                            let state = handle.state::<Backend>();
                            let mut guard = state.0.lock().unwrap();
                            match guard.as_mut() {
                                Some(child) => child
                                    .try_wait()
                                    .map(|o| o.is_some())
                                    .unwrap_or(false),
                                None => true,
                            }
                        };
                        if died {
                            break;
                        }
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
                    // 已有外部后端在跑：不持有其句柄（避免退出时误杀别人的进程），
                    // 但仍需 watchdog——更新重启竞态中旧壳会 taskkill 掉这个后端，
                    // 新壳若不接管重拉，WebView 将指向死端口
                    std::thread::spawn(move || loop {
                        std::thread::sleep(Duration::from_secs(3));
                        if backend_ready(port) {
                            continue;
                        }
                        eprintln!("[learnflow] 外部后端已失联，尝试重新拉起…");
                        let child = spawn_backend(&handle, port);
                        *handle.state::<Backend>().0.lock().unwrap() = child;
                        // 等待自拉后端就绪；进程闪退则回到循环重试
                        for _ in 0..20 {
                            std::thread::sleep(Duration::from_millis(600));
                            if backend_ready(port) {
                                break;
                            }
                        }
                        if backend_ready(port) {
                            eprintln!("[learnflow] 后端已恢复");
                            if let Some(win) = handle.get_webview_window("main") {
                                let _ = win.eval(&format!(
                                    "if(!location.href.startsWith('http://127.0.0.1:{port}'))location.replace('http://127.0.0.1:{port}/');"
                                ));
                            }
                        }
                    });
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
                    // 已被 try_wait() reap 过的后端（如中途闪退）不再 taskkill：
                    // Windows PID 会被复用，对旧 PID 执行 /T 可能误杀无关进程树
                    let already_exited = matches!(child.try_wait(), Ok(Some(_)));
                    if !already_exited {
                        // Windows 下 kill() 只杀直接子进程：后端自身的孙进程（编译器/沙箱代码等）
                        // 会成为孤儿继续锁住安装目录。taskkill /T 级联终止整棵进程树。
                        // 用 spawn 而非 output()：不阻塞退出路径（AV 拦截 taskkill 时不让关机卡死），
                        // 子进程独立存活不受本进程退出影响。
                        #[cfg(windows)]
                        {
                            use std::os::windows::process::CommandExt;
                            let _ = Command::new("taskkill")
                                .args(["/F", "/T", "/PID", &child.id().to_string()])
                                .creation_flags(0x0800_0000) // CREATE_NO_WINDOW
                                .spawn();
                        }
                        #[cfg(not(windows))]
                        {
                            let _ = child.kill();
                        }
                    }
                    // taskkill 是异步的：进程尚未退出时 wait() 会阻塞退出路径（AV 拦截时尤甚）。
                    // 改为轮询 try_wait 最多等 3 秒；超时放弃等待继续退出，
                    // 子进程句柄由 OS 在本进程结束后回收，进程树由 taskkill /T 结束。
                    let deadline = std::time::Instant::now() + Duration::from_secs(3);
                    loop {
                        match child.try_wait() {
                            Ok(Some(_)) => break,
                            Ok(None) => {
                                if std::time::Instant::now() >= deadline {
                                    break;
                                }
                                std::thread::sleep(Duration::from_millis(50));
                            }
                            Err(_) => break,
                        }
                    }
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
