import type { Node } from "./types";

interface Props {
  node: Node | null;
  onClose: () => void;
}

function formatJSON(obj: unknown): string {
  try {
    return JSON.stringify(obj, null, 2);
  } catch {
    return String(obj);
  }
}

function hasKeys(o: Record<string, unknown> | null | undefined): boolean {
  return !!o && Object.keys(o).length > 0;
}

export function NodeDetails({ node, onClose }: Props) {
  if (!node) return null;

  return (
    <div className="drawer">
      <div className="drawer-header">
        <h3>{node.node_name}</h3>
        <button className="drawer-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>

      <section className="drawer-section">
        <h4>Identity</h4>
        <dl className="kv">
          <dt>kind</dt>
          <dd>{node.kind}</dd>
          <dt>id</dt>
          <dd className="mono">{node.id.slice(0, 8)}…</dd>
          <dt>step</dt>
          <dd>#{node.step_index}</dd>
          {node.parent_node_id ? (
            <>
              <dt>parent</dt>
              <dd className="mono">{node.parent_node_id.slice(0, 8)}…</dd>
            </>
          ) : null}
          {node.model_name ? (
            <>
              <dt>model</dt>
              <dd>{node.model_name}</dd>
            </>
          ) : null}
          {node.tool_name ? (
            <>
              <dt>tool</dt>
              <dd>{node.tool_name}</dd>
            </>
          ) : null}
        </dl>
      </section>

      {hasKeys(node.tool_input) ? (
        <section className="drawer-section">
          <h4>Tool input</h4>
          <pre>{formatJSON(node.tool_input)}</pre>
        </section>
      ) : null}

      {hasKeys(node.tool_output) ? (
        <section className="drawer-section">
          <h4>Tool output</h4>
          <pre>{formatJSON(node.tool_output)}</pre>
        </section>
      ) : null}

      {node.usage ? (
        <section className="drawer-section">
          <h4>Usage</h4>
          <dl className="kv">
            <dt>prompt</dt>
            <dd>{node.usage.prompt_tokens ?? "—"}</dd>
            <dt>completion</dt>
            <dd>{node.usage.completion_tokens ?? "—"}</dd>
            <dt>total</dt>
            <dd>{node.usage.total_tokens ?? "—"}</dd>
            {node.cost_usd_cents != null ? (
              <>
                <dt>cost</dt>
                <dd>${(node.cost_usd_cents / 100).toFixed(4)}</dd>
              </>
            ) : null}
          </dl>
        </section>
      ) : null}

      {node.error_message ? (
        <section className="drawer-section">
          <h4 style={{ color: "var(--err)" }}>Error</h4>
          <pre style={{ color: "var(--err)" }}>{node.error_message}</pre>
        </section>
      ) : null}

      {hasKeys(node.state_after) ? (
        <section className="drawer-section">
          <h4>State after</h4>
          <pre>{formatJSON(node.state_after)}</pre>
        </section>
      ) : null}

      {hasKeys(node.metadata) ? (
        <section className="drawer-section">
          <h4>Metadata</h4>
          <pre>{formatJSON(node.metadata)}</pre>
        </section>
      ) : null}

      <section className="drawer-section">
        <h4>Timestamps</h4>
        <dl className="kv">
          <dt>started</dt>
          <dd className="mono">{node.started_at}</dd>
          <dt>ended</dt>
          <dd className="mono">{node.ended_at ?? "—"}</dd>
        </dl>
      </section>
    </div>
  );
}
