import { useEffect, useState } from "react";
import { connectLiveSocket, listSites } from "./api/client";
import { Factory } from "./components/Factory";
import { Household } from "./components/Household";
import type { LiveSnapshot, Site } from "./api/types";

export default function App() {
  const [sites, setSites] = useState<Site[]>([]);
  const [tab, setTab] = useState<"household" | "factory">("household");
  const [live, setLive] = useState<LiveSnapshot | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    listSites().then(setSites);
    const ws = connectLiveSocket((data) => {
      if (data.type === "live_snapshot") setLive(data);
    });
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    return () => ws.close();
  }, []);

  const householdSite = sites.find((s) => s.type === "household");
  const factorySite = sites.find((s) => s.type === "factory");

  return (
    <div className="app">
      <header>
        <h1>Home &amp; factory automation console</h1>
        <span className={`badge ${connected ? "badge-online" : "badge-offline"}`}>
          {connected ? "live" : "connecting..."}
        </span>
      </header>

      <nav className="tabs">
        <button className={tab === "household" ? "tab active" : "tab"} onClick={() => setTab("household")}>
          Household
        </button>
        <button className={tab === "factory" ? "tab active" : "tab"} onClick={() => setTab("factory")}>
          Factory
        </button>
      </nav>

      <main>
        {tab === "household" && householdSite && <Household site={householdSite} live={live} />}
        {tab === "factory" && factorySite && <Factory site={factorySite} live={live} />}
        {tab === "household" && !householdSite && <p className="empty">waiting for the simulator to create a household site...</p>}
        {tab === "factory" && !factorySite && <p className="empty">waiting for the simulator to create a factory site...</p>}
      </main>
    </div>
  );
}
