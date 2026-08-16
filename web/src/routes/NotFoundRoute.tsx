import { Link } from "react-router-dom";

export function NotFoundRoute() {
  return (
    <section className="placeholder" data-testid="not-found">
      <h2>No such view</h2>
      <p className="placeholder-summary">
        That address does not match any view in this app. <Link to="/">Back to the dashboard</Link>.
      </p>
    </section>
  );
}
