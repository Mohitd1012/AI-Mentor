use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager,
};

mod sidecar;
mod right_cmd_monitor;

#[tauri::command]
fn get_backend_url() -> String {
    "ws://localhost:8765/ws".to_string()
}

#[tauri::command]
async fn check_backend_health() -> Result<bool, String> {
    match reqwest::get("http://localhost:8765/health").await {
        Ok(r) => Ok(r.status().is_success()),
        Err(_) => Ok(false),
    }
}

#[tauri::command]
fn get_ptt_shortcut() -> String {
    "Right ⌘".to_string()
}

/// Force a WebviewWindow to be fully transparent at the OS layer.
///
/// NOTE: On macOS 26 (Tahoe) the WKWebView still paints an opaque layer
/// behind the page even after this call. A native AppKit fix was attempted
/// but crashes on some view subclasses; tracking this as a known issue.
fn force_window_transparent(win: &tauri::WebviewWindow) {
    let _ = win.set_background_color(Some(tauri::window::Color(0, 0, 0, 0)));
}

#[tauri::command]
async fn overlay_show(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("overlay") {
        // Re-apply transparency every time we show — defensive against
        // any state the WebView might have stashed since last hide.
        force_window_transparent(&win);

        // Resize to full primary monitor, click-through, then show
        if let Ok(Some(monitor)) = win.current_monitor() {
            let size = monitor.size();
            let pos  = monitor.position();
            let _ = win.set_position(tauri::PhysicalPosition::new(pos.x, pos.y));
            let _ = win.set_size(tauri::PhysicalSize::new(size.width, size.height));
        }
        win.set_ignore_cursor_events(true).map_err(|e| e.to_string())?;
        win.show().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
async fn overlay_hide(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("overlay") {
        win.hide().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
async fn overlay_annotate(
    app: tauri::AppHandle,
    payload: serde_json::Value,
) -> Result<(), String> {
    // Make sure the overlay is showing first
    overlay_show(app.clone()).await?;
    if let Some(win) = app.get_webview_window("overlay") {
        win.emit("overlay:annotate", payload).map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
async fn overlay_clear(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("overlay") {
        win.emit("overlay:clear", ()).map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .setup(|app| {
            // Launch Python sidecar backend
            sidecar::spawn_backend(app.handle())?;

            // Force overlay transparency before it ever paints.
            // (Fixes the macOS 13+ WKWebView underPageBackgroundColor
            //  that otherwise turns the overlay white/black.)
            if let Some(overlay) = app.get_webview_window("overlay") {
                force_window_transparent(&overlay);
            }

            // ── Global PTT trigger: Right Command (bare modifier) ──────────────
            let handle = app.handle().clone();
            right_cmd_monitor::install(move |pressed| {
                let event = if pressed { "global-ptt-start" } else { "global-ptt-stop" };
                let _ = handle.emit(event, ());
            });

            // System tray
            let quit = MenuItem::with_id(app, "quit", "Quit AI Mentor", true, None::<&str>)?;
            let show = MenuItem::with_id(app, "show", "Show / Hide", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;

            TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "quit" => app.exit(0),
                    "show" => {
                        if let Some(win) = app.get_webview_window("main") {
                            if win.is_visible().unwrap_or(false) {
                                let _ = win.hide();
                            } else {
                                let _ = win.show();
                                let _ = win.set_focus();
                            }
                        }
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(win) = app.get_webview_window("main") {
                            if win.is_visible().unwrap_or(false) {
                                let _ = win.hide();
                            } else {
                                let _ = win.show();
                                let _ = win.set_focus();
                            }
                        }
                    }
                })
                .build(app)?;

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_backend_url,
            check_backend_health,
            get_ptt_shortcut,
            overlay_show,
            overlay_hide,
            overlay_annotate,
            overlay_clear,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
