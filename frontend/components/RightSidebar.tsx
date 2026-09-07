"use client";

import { useEffect, useState } from "react";
import { CalendarDays, CircleCheck, GripVertical, ListTodo, Plus, Trash2, Wallet } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8300";

type Tab = "tasks" | "schedule" | "expenses";

type Task = { id: string; title: string; status: string; dueAt: string | null };
type CalendarEvent = { id: string; summary: string; start: string; end: string };
type Transaction = { id: string; categoryId: string; categoryName: string; amount: number; direction: string };
type BudgetSummary = { spent: number; leftToSpend: number } | null;

async function apiFetch(path: string, options?: RequestInit) {
  const resp = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (resp.status === 401) {
    window.location.href = "/login";
    throw new Error("Not logged in");
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed (${resp.status})`);
  }
  return resp.status === 204 ? null : resp.json();
}

function formatMoney(minor: number): string {
  return (minor / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// A <input type="datetime-local"> value ("2026-10-05T20:00") has no
// timezone of its own -- the browser's own local time is this device's
// real location, so that's the correct zone to attach, not a guess.
function toIsoWithOffset(datetimeLocal: string): string {
  const date = new Date(datetimeLocal);
  const offsetMin = -date.getTimezoneOffset();
  const sign = offsetMin >= 0 ? "+" : "-";
  const pad = (n: number) => String(Math.abs(n)).padStart(2, "0");
  const offset = `${sign}${pad(Math.floor(Math.abs(offsetMin) / 60))}:${pad(Math.abs(offsetMin) % 60)}`;
  return `${datetimeLocal}:00${offset}`;
}

function formatEventTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  } catch {
    return iso;
  }
}

export default function RightSidebar({ hidden }: { hidden: boolean }) {
  const [tab, setTab] = useState<Tab>("tasks");

  return (
    <aside className={`right-sidebar ${hidden ? "sidebar-hidden" : ""}`}>
      <div className="right-tabs">
        <button type="button" className={`right-tab ${tab === "tasks" ? "active" : ""}`} onClick={() => setTab("tasks")}>
          <ListTodo size={15} /> Tasks
        </button>
        <button type="button" className={`right-tab ${tab === "schedule" ? "active" : ""}`} onClick={() => setTab("schedule")}>
          <CalendarDays size={15} /> Schedule
        </button>
        <button type="button" className={`right-tab ${tab === "expenses" ? "active" : ""}`} onClick={() => setTab("expenses")}>
          <Wallet size={15} /> Expenses
        </button>
      </div>
      <div className="right-tab-content">
        {tab === "tasks" && <TasksPanel />}
        {tab === "schedule" && <SchedulePanel />}
        {tab === "expenses" && <ExpensesPanel />}
      </div>
    </aside>
  );
}

function TasksPanel() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [newTitle, setNewTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);

  async function refresh() {
    try {
      setTasks(await apiFetch("/api/tasks"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load tasks");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function addTask() {
    const title = newTitle.trim();
    if (!title) return;
    setNewTitle("");
    try {
      await apiFetch("/api/tasks", { method: "POST", body: JSON.stringify({ title }) });
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add task");
    }
  }

  async function toggleDone(task: Task) {
    const status = task.status === "DONE" ? "TODO" : "DONE";
    setTasks((prev) => prev.map((t) => (t.id === task.id ? { ...t, status } : t)));
    try {
      await apiFetch(`/api/tasks/${task.id}`, { method: "PATCH", body: JSON.stringify({ status }) });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update task");
      refresh();
    }
  }

  async function commitEdit(id: string) {
    const title = editingTitle.trim();
    setEditingId(null);
    if (!title) return;
    setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, title } : t)));
    try {
      await apiFetch(`/api/tasks/${id}`, { method: "PATCH", body: JSON.stringify({ title }) });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to rename task");
      refresh();
    }
  }

  async function removeTask(id: string) {
    setTasks((prev) => prev.filter((t) => t.id !== id));
    try {
      await apiFetch(`/api/tasks/${id}`, { method: "DELETE" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete task");
      refresh();
    }
  }

  function handleDrop(targetId: string) {
    setDragOverId(null);
    const sourceId = draggedId;
    setDraggedId(null);
    if (!sourceId || sourceId === targetId) return;

    setTasks((prev) => {
      const next = [...prev];
      const from = next.findIndex((t) => t.id === sourceId);
      const to = next.findIndex((t) => t.id === targetId);
      if (from === -1 || to === -1) return prev;
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);

      apiFetch("/api/tasks/reorder", { method: "POST", body: JSON.stringify({ task_ids: next.map((t) => t.id) }) }).catch(
        (e) => {
          setError(e instanceof Error ? e.message : "Failed to save the new order");
          refresh();
        }
      );

      return next;
    });
  }

  return (
    <div className="panel">
      <div className="panel-add-row">
        <input
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addTask()}
          placeholder="Add a task…"
        />
        <button type="button" onClick={addTask} title="Add task">
          <Plus size={16} />
        </button>
      </div>
      {error && <div className="panel-error">{error}</div>}
      <div className="panel-list">
        {tasks.length === 0 && !error && <div className="panel-empty">No tasks</div>}
        {tasks.map((t) => (
          <div
            key={t.id}
            className={`panel-item ${dragOverId === t.id ? "drag-over" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              if (dragOverId !== t.id) setDragOverId(t.id);
            }}
            onDragLeave={() => setDragOverId((id) => (id === t.id ? null : id))}
            onDrop={(e) => {
              e.preventDefault();
              handleDrop(t.id);
            }}
          >
            <span
              className="item-drag-handle"
              draggable
              onDragStart={() => setDraggedId(t.id)}
              onDragEnd={() => {
                setDraggedId(null);
                setDragOverId(null);
              }}
              title="Drag to reorder"
            >
              <GripVertical size={14} />
            </span>
            <button
              type="button"
              className={`item-check ${t.status === "DONE" ? "checked" : ""}`}
              onClick={() => toggleDone(t)}
              title={t.status === "DONE" ? "Mark as not done" : "Mark as done"}
            >
              {t.status === "DONE" && <CircleCheck size={16} />}
            </button>
            {editingId === t.id ? (
              <input
                className="item-edit-input"
                value={editingTitle}
                autoFocus
                onChange={(e) => setEditingTitle(e.target.value)}
                onBlur={() => commitEdit(t.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                  if (e.key === "Escape") setEditingId(null);
                }}
              />
            ) : (
              <span
                className={`item-title ${t.status === "DONE" ? "done" : ""}`}
                onClick={() => {
                  setEditingId(t.id);
                  setEditingTitle(t.title);
                }}
              >
                {t.title}
              </span>
            )}
            <button type="button" className="item-delete" onClick={() => removeTask(t.id)} title="Delete">
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function SchedulePanel() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [summary, setSummary] = useState("");
  const [start, setStart] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingSummary, setEditingSummary] = useState("");

  async function refresh() {
    try {
      setEvents(await apiFetch("/api/calendar/events"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load calendar events");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function addEvent() {
    const title = summary.trim();
    if (!title || !start) return;
    setSummary("");
    setStart("");
    try {
      await apiFetch("/api/calendar/events", {
        method: "POST",
        body: JSON.stringify({ summary: title, start: toIsoWithOffset(start) }),
      });
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add event");
    }
  }

  async function commitEdit(id: string) {
    const title = editingSummary.trim();
    setEditingId(null);
    if (!title) return;
    setEvents((prev) => prev.map((ev) => (ev.id === id ? { ...ev, summary: title } : ev)));
    try {
      await apiFetch(`/api/calendar/events/${id}`, { method: "PATCH", body: JSON.stringify({ summary: title }) });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to rename event");
      refresh();
    }
  }

  async function removeEvent(id: string) {
    setEvents((prev) => prev.filter((ev) => ev.id !== id));
    try {
      await apiFetch(`/api/calendar/events/${id}`, { method: "DELETE" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete event");
      refresh();
    }
  }

  return (
    <div className="panel">
      <div className="panel-add-row column">
        <input value={summary} onChange={(e) => setSummary(e.target.value)} placeholder="Event title…" />
        <div className="panel-add-row">
          <input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />
          <button type="button" onClick={addEvent} title="Add event">
            <Plus size={16} />
          </button>
        </div>
      </div>
      {error && <div className="panel-error">{error}</div>}
      <div className="panel-list">
        {events.length === 0 && !error && <div className="panel-empty">Nothing scheduled</div>}
        {events.map((ev) => (
          <div key={ev.id} className="panel-item">
            <div className="item-main">
              {editingId === ev.id ? (
                <input
                  className="item-edit-input"
                  value={editingSummary}
                  autoFocus
                  onChange={(e) => setEditingSummary(e.target.value)}
                  onBlur={() => commitEdit(ev.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                    if (e.key === "Escape") setEditingId(null);
                  }}
                />
              ) : (
                <span
                  className="item-title"
                  onClick={() => {
                    setEditingId(ev.id);
                    setEditingSummary(ev.summary);
                  }}
                >
                  {ev.summary}
                </span>
              )}
              <span className="item-subtext">{formatEventTime(ev.start)}</span>
            </div>
            <button type="button" className="item-delete" onClick={() => removeEvent(ev.id)} title="Delete">
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function ExpensesPanel() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [budget, setBudget] = useState<BudgetSummary>(null);
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const [txs, summaryResp] = await Promise.all([apiFetch("/api/budget/transactions"), apiFetch("/api/budget/summary")]);
      setTransactions(txs);
      setBudget(summaryResp.summary);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load budget");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function addExpense() {
    const value = parseFloat(amount);
    const cat = category.trim();
    if (!value || !cat) return;
    setAmount("");
    setCategory("");
    try {
      await apiFetch("/api/budget/transactions", {
        method: "POST",
        body: JSON.stringify({ amount_minor: Math.round(value * 100), category_name: cat, direction: "EXPENSE" }),
      });
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add expense");
    }
  }

  async function removeTransaction(id: string) {
    setTransactions((prev) => prev.filter((t) => t.id !== id));
    try {
      await apiFetch(`/api/budget/transactions/${id}`, { method: "DELETE" });
      refresh(); // the budget summary's totals need refreshing too, not just the list
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete transaction");
      refresh();
    }
  }

  return (
    <div className="panel">
      {budget && (
        <div className="budget-strip">
          <span>Spent: {formatMoney(budget.spent)}</span>
          <span>Left: {formatMoney(budget.leftToSpend)}</span>
        </div>
      )}
      <div className="panel-add-row">
        <input
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="Amount"
          inputMode="decimal"
          className="amount-input"
        />
        <input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Category" />
        <button type="button" onClick={addExpense} title="Add expense">
          <Plus size={16} />
        </button>
      </div>
      {error && <div className="panel-error">{error}</div>}
      <div className="panel-list">
        {transactions.length === 0 && !error && <div className="panel-empty">No transactions this month</div>}
        {transactions.map((t) => (
          <div key={t.id} className="panel-item">
            <div className="item-main">
              <span className="item-title">{t.categoryName}</span>
              <span className={`item-subtext ${t.direction === "REFUND" ? "positive" : ""}`}>
                {t.direction === "REFUND" ? "+" : "-"}
                {formatMoney(t.amount)}
              </span>
            </div>
            <button type="button" className="item-delete" onClick={() => removeTransaction(t.id)} title="Delete">
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
