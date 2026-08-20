export default function Loading() {
  return (
    <main className="loading-shell" aria-busy="true" aria-label="Loading dashboard">
      <div className="loading-bar" />
      <div className="loading-hero" />
      <div className="loading-grid">
        <div />
        <div />
        <div />
        <div />
      </div>
      <p>Loading the paper research desk…</p>
    </main>
  );
}
