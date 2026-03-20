export default function AlertsPage() {
  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Alerts</h1>
      <div className="flex items-center justify-center h-64 border border-terminal-border rounded-md bg-terminal-bg-secondary">
        <p className="text-terminal-text-secondary">No active alerts. Configure price and event alerts.</p>
      </div>
    </div>
  );
}
