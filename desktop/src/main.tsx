import { createRoot } from 'react-dom/client'
import './monaco'
import App from './App'
import { AppProvider } from './store'
import './styles.css'

const root = document.getElementById('root')
if (!root) throw new Error('#root 不存在')
createRoot(root).render(<AppProvider><App /></AppProvider>)
