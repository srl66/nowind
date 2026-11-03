/// Tauri v2 入口。前端是纯静态资源，暂无自定义 command；
/// 后续要直连本地中间件时，在这里注册 #[tauri::command] 或开启 http 插件。
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
