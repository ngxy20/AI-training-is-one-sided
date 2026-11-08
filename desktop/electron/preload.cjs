const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('aixianDesktop', {
  openPath: (options) => ipcRenderer.invoke('dialog:openPath', options || {}),
  info: () => ipcRenderer.invoke('app:info'),
  openExternal: (url) => ipcRenderer.invoke('shell:openExternal', url),
  isDesktop: true,
})
