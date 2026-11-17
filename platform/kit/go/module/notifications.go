package module

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"time"
)

// Workbench's bell polls every module's GET /v1/notifications for the person, every 30 seconds
// for each open tab, and posts POST /v1/notifications/read when they've seen some. Register
// answers both: with a Notifier, from it; without one, an empty page, so a module without
// notifications needs nothing.

// Notification is one thing a person should know about, as Workbench's bell shows it.
type Notification struct {
	ID string `json:"id"`
	// ReadAt is when they read it; nil while it's unread.
	ReadAt *time.Time `json:"read_at"`
	// To is the page it leads to, under the app's /t/<tenant>/.
	To string `json:"to,omitempty"`
	// Target names the record, <module>:<type>:<id>, for a module whose records Workbench links.
	Target string `json:"target,omitempty"`
	Title  string `json:"title,omitempty"`
	// Event.Kind is what happened, such as task.assigned; the manifest's events label it.
	Event struct {
		Kind string `json:"kind"`
	} `json:"event"`
}

// Notifier is a module's notifications for one person.
type Notifier interface {
	// Notifications are this person's, changed since cursor ("" for all), at most limit, and
	// the cursor to ask from next time. Return one again when it's read, with ReadAt set.
	Notifications(ctx context.Context, c Caller, cursor string, limit int) ([]Notification, string, error)
	// MarkRead marks these of this person's read; any that aren't theirs are left alone.
	MarkRead(ctx context.Context, c Caller, ids []string) error
}

func (m *Module) notifications(w http.ResponseWriter, r *http.Request) {
	c, ok := m.Person(w, r)
	if !ok {
		return
	}
	cursor := r.URL.Query().Get("after")
	if m.Notifier == nil {
		Reply(w, 200, map[string]any{"notifications": []Notification{}, "cursor": cursor})
		return
	}
	limit, err := strconv.Atoi(r.URL.Query().Get("limit"))
	if err != nil || limit <= 0 || limit > 200 {
		limit = 200
	}
	list, next, err := m.Notifier.Notifications(r.Context(), c, cursor, limit)
	if err != nil {
		Reply(w, 503, map[string]string{"error": "notifications_unavailable"})
		return
	}
	if list == nil {
		list = []Notification{}
	}
	Reply(w, 200, map[string]any{"notifications": list, "cursor": next})
}

func (m *Module) markRead(w http.ResponseWriter, r *http.Request) {
	c, ok := m.Person(w, r)
	if !ok {
		return
	}
	var body struct {
		IDs []string `json:"ids"`
	}
	if json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&body) != nil {
		Reply(w, 400, map[string]string{"error": "invalid_request"})
		return
	}
	if m.Notifier != nil && len(body.IDs) > 0 {
		if err := m.Notifier.MarkRead(r.Context(), c, body.IDs); err != nil {
			Reply(w, 503, map[string]string{"error": "notifications_unavailable"})
			return
		}
	}
	w.WriteHeader(http.StatusNoContent)
}
