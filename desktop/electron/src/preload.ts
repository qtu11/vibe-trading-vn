import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("vibeDesktop", {
  isDesktop: true,
  sourceBrowser: {
    open: (url: string, bounds: { x: number; y: number; width: number; height: number }) => ipcRenderer.invoke("desktop:source-open", url, bounds),
    setBounds: (bounds: { x: number; y: number; width: number; height: number }) => ipcRenderer.send("desktop:source-bounds", bounds),
    close: () => ipcRenderer.send("desktop:source-close"),
    navigate: (action: string) => ipcRenderer.send("desktop:source-navigate", action),
    openExternal: (url: string) => ipcRenderer.send("desktop:source-external", url),
    onState: (callback: (state: unknown) => void) => {
      const listener = (_event: Electron.IpcRendererEvent, state: unknown) => callback(state);
      ipcRenderer.on("desktop:source-state", listener);
      return () => ipcRenderer.removeListener("desktop:source-state", listener);
    },
  },
  onStatus: (callback: (message: string) => void) => {
    ipcRenderer.on("desktop:status", (_event, message: string) => callback(message));
  },
  onError: (callback: (message: string) => void) => {
    ipcRenderer.on("desktop:error", (_event, message: string) => callback(message));
  },
  retry: () => ipcRenderer.send("desktop:retry"),
  openLogs: () => ipcRenderer.send("desktop:open-logs"),
  restartBackend: () => ipcRenderer.invoke("desktop:restart-backend") as Promise<boolean>,
  getCredentialStatus: () => ipcRenderer.invoke("desktop:get-credential-status"),
  setCredential: (name: string, value: string | null) =>
    ipcRenderer.invoke("desktop:set-credential", name, value),
});
