use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::thread;
use std::time::Duration;
use tauri::{AppHandle, Manager};

/// Port the Python backend listens on. Mirrors the value in backend/config.py.
const BACKEND_PORT: u16 = 8765;

/// Environment variable to force-skip the auto-spawn. Useful when the user
/// wants to run `python main.py` themselves (e.g. under a debugger).
const SKIP_ENV_VAR: &str = "MENTOR_NO_SIDECAR";

/// Returns true if something is already accepting connections on the backend
/// port. A short TCP-connect probe — no HTTP roundtrip needed.
fn backend_already_running() -> bool {
    let addr = format!("127.0.0.1:{}", BACKEND_PORT);
    matches!(
        TcpStream::connect_timeout(
            &addr.parse().expect("valid socket addr"),
            Duration::from_millis(150),
        ),
        Ok(_)
    )
}

pub fn spawn_backend(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    // Explicit opt-out: developer started the backend manually.
    if std::env::var(SKIP_ENV_VAR).is_ok() {
        println!("[sidecar] {} set — skipping auto-spawn", SKIP_ENV_VAR);
        return Ok(());
    }

    // Implicit opt-out: something is already on the port (probably you running
    // `python main.py` in another terminal). Don't conflict.
    if backend_already_running() {
        println!(
            "[sidecar] Detected existing backend on :{} — attaching to it instead of spawning.\n  \
             (Stop it first if you want Tauri to manage the backend process.)",
            BACKEND_PORT
        );
        return Ok(());
    }

    let app_dir = app
        .path()
        .app_data_dir()
        .unwrap_or_else(|_| PathBuf::from("."));

    let backend_path = if cfg!(debug_assertions) {
        // Dev exe lives at:  <project>/desktop/src-tauri/target/debug/desktop
        let exe = std::env::current_exe().unwrap();
        let ancestors: Vec<_> = exe.ancestors().collect();
        let root = ancestors
            .get(5)
            .copied()
            .unwrap_or_else(|| ancestors.last().unwrap());
        root.join("backend")
    } else {
        app_dir.join("backend")
    };

    let main_py = backend_path.join("main.py");
    let venv_python = backend_path.join(".venv/bin/python3");

    if !main_py.exists() {
        eprintln!(
            "[sidecar] ERROR: Backend not found.\n  Looked for: {:?}\n  \
             Make sure the project structure is intact.",
            main_py
        );
        return Ok(());
    }

    let python = if venv_python.exists() {
        venv_python
    } else {
        eprintln!(
            "[sidecar] venv not found at {:?} — using system python3",
            backend_path.join(".venv")
        );
        PathBuf::from("python3")
    };

    println!("[sidecar] Starting backend: {:?} {:?}", python, main_py);

    thread::spawn(move || {
        let result = Command::new(&python)
            .arg(&main_py)
            .current_dir(&backend_path)
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .spawn();

        match result {
            Ok(mut child) => {
                println!("[sidecar] Backend started (pid {})", child.id());
                let _ = child.wait();
                println!("[sidecar] Backend exited");
            }
            Err(e) => {
                eprintln!("[sidecar] Failed to start backend with {:?}: {}", python, e);
            }
        }
    });

    Ok(())
}
