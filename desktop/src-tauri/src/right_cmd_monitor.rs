//! Right Command bare-modifier monitor (macOS only).
//!
//! Tauri's `global-shortcut` plugin (and the underlying `global-hotkey` crate)
//! cannot detect a bare modifier press — they require a non-modifier key.
//!
//! We listen at the HID level via Core Graphics' `CGEventTap`, watching
//! `flagsChanged` events. We distinguish Left vs Right Command by the raw
//! keycode (kVK_Command=0x37, kVK_RightCommand=0x36) and determine press vs
//! release from the modifier-flag bit transition.
//!
//! The tap is `ListenOnly` — we observe events but do not modify them, so
//! Right Cmd continues to function normally for any keyboard shortcuts you
//! happen to use it with.

use core_foundation::base::TCFType;
use core_foundation::runloop::{
    kCFRunLoopCommonModes, CFRunLoop, CFRunLoopAddSource, CFRunLoopGetCurrent, CFRunLoopRun,
};
use core_graphics::event::{
    CGEventFlags, CGEventTap, CGEventTapLocation, CGEventTapOptions, CGEventTapPlacement,
    CGEventType, EventField,
};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;

const KVK_RIGHT_COMMAND: i64 = 0x36;

/// Install a global Right-Command listener.
/// `on_change(true)`  — Right Cmd pressed
/// `on_change(false)` — Right Cmd released
///
/// Spawns a dedicated thread that owns a CFRunLoop. Returns immediately.
pub fn install<F>(on_change: F)
where
    F: Fn(bool) + Send + Sync + 'static,
{
    let cb = Arc::new(on_change);
    let pressed = Arc::new(AtomicBool::new(false));

    thread::Builder::new()
        .name("right-cmd-monitor".into())
        .spawn(move || {
            let cb_for_tap = cb.clone();
            let pressed_for_tap = pressed.clone();

            // CGEventTap callback runs on this thread's run loop.
            let tap = match CGEventTap::new(
                CGEventTapLocation::HID,
                CGEventTapPlacement::HeadInsertEventTap,
                CGEventTapOptions::ListenOnly,
                vec![CGEventType::FlagsChanged],
                move |_proxy, event_type, event| {
                    if matches!(event_type, CGEventType::FlagsChanged) {
                        let keycode =
                            event.get_integer_value_field(EventField::KEYBOARD_EVENT_KEYCODE);
                        if keycode == KVK_RIGHT_COMMAND {
                            let flags = event.get_flags();
                            let cmd_down = flags.contains(CGEventFlags::CGEventFlagCommand);
                            let was_down = pressed_for_tap.swap(cmd_down, Ordering::SeqCst);
                            if cmd_down != was_down {
                                cb_for_tap(cmd_down);
                            }
                        }
                    }
                    None
                },
            ) {
                Ok(t) => t,
                Err(e) => {
                    eprintln!(
                        "[right-cmd] failed to create event tap: {:?}\n\
                         → grant Accessibility permission in System Settings",
                        e
                    );
                    return;
                }
            };

            // Attach to this thread's run loop and start it.
            unsafe {
                let loop_source = tap
                    .mach_port
                    .create_runloop_source(0)
                    .expect("Failed to create run-loop source");
                let current = CFRunLoop::wrap_under_get_rule(CFRunLoopGetCurrent());
                CFRunLoopAddSource(
                    current.as_concrete_TypeRef(),
                    loop_source.as_concrete_TypeRef(),
                    kCFRunLoopCommonModes,
                );
                tap.enable();
                println!("[right-cmd] monitor active — hold Right Command to talk");
                CFRunLoopRun();
            }
        })
        .expect("failed to spawn right-cmd-monitor thread");
}
