import { useState } from 'react'
import MainMapPage from './pages/MainMapPage'
import NavigationPointsPage from './pages/NavigationPointsPage'
import PolygonWaypointPage from './pages/PolygonWaypointPage'
import ChatPage from './pages/ChatPage'

type Page = 'main' | 'navpoints' | 'polygon' | 'chat'

export default function App() {
  const [page, setPage] = useState<Page>('main')

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">ROS2 Web Nav</div>
        <button className={page === 'main' ? 'active' : ''} onClick={() => setPage('main')}>Main Map</button>
        <button className={page === 'navpoints' ? 'active' : ''} onClick={() => setPage('navpoints')}>Navigation Points</button>
        <button className={page === 'polygon' ? 'active' : ''} onClick={() => setPage('polygon')}>Polygon Tool</button>
        <button className={page === 'chat' ? 'active' : ''} onClick={() => setPage('chat')}>Chat</button>
      </aside>
      <main className="page">
        {page === 'main' && <MainMapPage />}
        {page === 'navpoints' && <NavigationPointsPage />}
        {page === 'polygon' && <PolygonWaypointPage />}
        {page === 'chat' && <ChatPage />}
      </main>
    </div>
  )
}
