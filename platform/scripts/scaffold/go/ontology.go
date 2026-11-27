package main

import (
	"cmp"
	"context"
	"fmt"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/xiant10/t10-modkit/module"
	"github.com/xiant10/t10-modkit/ontology"
	"github.com/xiant10/t10-modkit/ontology/proposals"
	"github.com/xiant10/t10-modkit/ontology/undo"
)

// The module's ontology (platform/docs/module.md, "Model its ontology"): its records as object
// types, and what may be done to them as action types, each over the module's own reads and
// commands. t10-modkit builds the descriptor at /v1/ontology, the object, action and proposal
// routes, and the __id___describe, _search, _get and _propose agent tools from them, so they
// can't drift apart. Agents only draft (tier propose); a person confirms each draft.
//
// The example is notes, kept in memory. Replace it with the module's own records, read and
// written through its own tables, and the stores with proposals.Postgres and undo.Postgres,
// whose Migrations go in the module's schema.

// useAction is the permission the example's actions need; a tenant admin holds every one.
const useAction = "__id__:use"

// ontologyVersion is the core's version: raise it whenever an object or action type changes.
const ontologyVersion = 1

type note struct {
	ID, Title, Body, State, Author string
	// Shared notes are for everyone in the company with __id__:use; the rest only for their author.
	Shared   bool
	Revision int64
	Updated  time.Time
}

// notes is the example's store: each tenant's notes.
type notes struct {
	mu      sync.Mutex
	tenants map[string][]*note
	seed    bool
}

// newNotes keeps notes in memory. With seed, each tenant starts with example notes, so the app
// and make contract have something to show when the module runs alone.
func newNotes(seed bool) *notes { return &notes{tenants: map[string][]*note{}, seed: seed} }

func (n *notes) tenant(id string) []*note {
	if _, ok := n.tenants[id]; !ok && n.seed {
		at := time.Date(2026, 1, 1, 9, 0, 0, 0, time.UTC)
		n.tenants[id] = []*note{
			{ID: "n_welcome", Title: "Welcome", Body: "An example note.", State: "open", Author: "usr_example", Shared: true, Revision: 1, Updated: at},
			{ID: "n_second", Title: "Second note", State: "open", Author: "usr_example", Shared: true, Revision: 1, Updated: at.Add(time.Hour)},
			{ID: "n_third", Title: "Third note", State: "open", Author: "usr_example", Shared: true, Revision: 1, Updated: at.Add(2 * time.Hour)},
			{ID: "n_private", Title: "Someone's own note", State: "open", Author: "usr_example", Revision: 1, Updated: at.Add(3 * time.Hour)},
			{ID: "n_archived", Title: "An archived note", State: "archived", Author: "usr_example", Shared: true, Revision: 1, Updated: at.Add(-time.Hour)},
		}
	}
	return n.tenants[id]
}

func canUse(c module.Caller) bool { return c.TenantAdmin || slices.Contains(c.Permissions, useAction) }

// visible is the example's scope: who may read a note. A module's own store puts it in its
// query, before sorting and paging, so a search never sees what a get would refuse.
func visible(c module.Caller, r note) bool { return canUse(c) && (r.Shared || r.Author == c.UserID) }

// newOntology declares the module's object and action types on s.Module.
func newOntology(s *Server, store *notes) {
	reg := s.NewOntology(ontology.Options[module.Caller]{
		Version: ontologyVersion, Proposals: &proposals.Memory{}, Undo: &undo.Memory{},
	})
	ontology.AddObject(reg, ontology.ObjectType[module.Caller, note]{
		Name: "note", Label: "Note", LabelZh: "笔记", Description: "A note someone in the company wrote.",
		Title: "title",
		Properties: map[string]ontology.Property{
			"title":      {Type: ontology.String, Name: "Title", NameZh: "标题"},
			"body":       {Type: ontology.Text, Name: "Text", NameZh: "内容"},
			"state":      {Type: ontology.Enum, Name: "State", NameZh: "状态", Values: []string{"open", "archived"}},
			"shared":     {Type: ontology.Boolean, Name: "Shared", NameZh: "共享"},
			"updated_at": {Type: ontology.Timestamp, Name: "Updated", NameZh: "更新时间"},
		},
		DefaultSort: ontology.Sort{Property: "updated_at", Desc: true},
		Search:      store.search,
		Get:         store.get,
		View: func(_ context.Context, _ module.Caller, r note) ontology.Object {
			return ontology.Object{ID: r.ID, Title: r.Title, Revision: r.Revision, Properties: map[string]any{
				"title": r.Title, "body": r.Body, "state": r.State, "shared": r.Shared, "updated_at": r.Updated.Format(time.RFC3339)}}
		},
	})
	open := func(_ context.Context, _ module.Caller, r note) string {
		if r.State != "open" {
			return "wrong_state"
		}
		return ""
	}
	ontology.AddAction(reg, ontology.ActionType[module.Caller, struct{}]{
		Name: "note.create", Label: "New note", LabelZh: "新建笔记", Description: "Write a new note.",
		Permission: useAction, Agent: ontology.Propose,
		Params: map[string]ontology.Param{
			"title":  {Type: ontology.String, Name: "Title", NameZh: "标题", Required: true},
			"body":   {Type: ontology.Text, Name: "Text", NameZh: "内容"},
			"shared": {Type: ontology.Boolean, Name: "Shared", NameZh: "共享"},
		},
		Apply: func(_ context.Context, c module.Caller, _ struct{}, in ontology.Input) (ontology.Result, error) {
			shared, _ := in.Params["shared"].(bool)
			id := store.create(c, str(in.Params["title"]), str(in.Params["body"]), shared)
			return ontology.Result{Type: "note", ID: id}, nil
		},
	})
	ontology.AddAction(reg, ontology.ActionType[module.Caller, note]{
		Name: "note.edit", On: "note", Label: "Edit", LabelZh: "编辑", Description: "Change an open note's title or text.",
		Permission: useAction, Agent: ontology.Propose, Available: open,
		Params: map[string]ontology.Param{
			"title": {Type: ontology.String, Name: "Title", NameZh: "标题"},
			"body":  {Type: ontology.Text, Name: "Text", NameZh: "内容"},
		},
		Apply: func(_ context.Context, c module.Caller, r note, in ontology.Input) (ontology.Result, error) {
			return ontology.Result{}, store.update(c, r.ID, in.Revision, func(n *note) {
				if t, ok := in.Params["title"]; ok {
					n.Title = str(t)
				}
				if b, ok := in.Params["body"]; ok {
					n.Body = str(b)
				}
			})
		},
	})
	ontology.AddAction(reg, ontology.ActionType[module.Caller, note]{
		Name: "note.archive", On: "note", Label: "Archive", LabelZh: "归档", Description: "Archive an open note. Only its author may.",
		Permission: useAction, Agent: ontology.Propose,
		Available: func(ctx context.Context, c module.Caller, r note) string {
			if r.Author != c.UserID {
				return "forbidden"
			}
			return open(ctx, c, r)
		},
		Apply: func(_ context.Context, c module.Caller, r note, in ontology.Input) (ontology.Result, error) {
			return ontology.Result{}, store.update(c, r.ID, in.Revision, func(n *note) { n.State = "archived" })
		},
	})
}

func str(v any) string {
	switch v := v.(type) {
	case nil:
		return ""
	case time.Time:
		return v.UTC().Format(time.RFC3339)
	}
	return fmt.Sprint(v)
}

// search answers the caller's tenant's notes, scope first, then filtered, sorted and paged.
func (n *notes) search(_ context.Context, c module.Caller, q ontology.Query) ([]note, error) {
	n.mu.Lock()
	defer n.mu.Unlock()
	var out []note
	for _, r := range n.tenant(c.TenantID) {
		if visible(c, *r) && (q.Filter == nil || matches(*r, *q.Filter)) {
			out = append(out, *r)
		}
	}
	// The sort value as a string that orders as the value does. Times are to the
	// second, as View answers them, so a page's cursor holds the same value.
	key := func(r note) string {
		switch q.Sort.Property {
		case "title":
			return r.Title
		case "body":
			return r.Body
		case "state":
			return r.State
		case "shared":
			return str(r.Shared)
		case "updated_at":
			return r.Updated.UTC().Format(time.RFC3339)
		}
		return ""
	}
	order := func(aKey, aID, bKey, bID string) int {
		d := cmp.Compare(aKey, bKey)
		if q.Sort.Desc {
			d = -d
		}
		return cmp.Or(d, cmp.Compare(aID, bID))
	}
	slices.SortFunc(out, func(a, b note) int { return order(key(a), a.ID, key(b), b.ID) })
	// A page starts after the cursor's sort value and ID, not after a row: that
	// row may since have changed, gone, or left the caller's scope. A store
	// does the same in SQL: WHERE sort > $value OR (sort = $value AND id > $id),
	// with < for a descending sort.
	if q.After != nil {
		after := str(q.After.Value)
		out = slices.DeleteFunc(out, func(r note) bool { return order(key(r), r.ID, after, q.After.ID) <= 0 })
	}
	return out[:min(len(out), q.Limit+1)], nil
}

// matches is a filter over the example's properties; a module's own store turns it into SQL.
func matches(r note, f ontology.Filter) bool {
	if len(f.And) > 0 {
		for _, g := range f.And {
			if !matches(r, g) {
				return false
			}
		}
		return true
	}
	value := map[string]string{"title": r.Title, "body": r.Body, "state": r.State, "shared": str(r.Shared), "updated_at": r.Updated.Format(time.RFC3339)}[f.Property]
	switch f.Op {
	case ontology.Eq:
		return value == str(f.Value)
	case ontology.In:
		list, _ := f.Value.([]any)
		return slices.ContainsFunc(list, func(v any) bool { return str(v) == value })
	case ontology.Contains:
		return strings.Contains(strings.ToLower(value), strings.ToLower(str(f.Value)))
	case ontology.Lt:
		return value < str(f.Value)
	case ontology.Gt:
		return value > str(f.Value)
	}
	return false
}

func (n *notes) get(_ context.Context, c module.Caller, id string) (note, error) {
	n.mu.Lock()
	defer n.mu.Unlock()
	for _, r := range n.tenant(c.TenantID) {
		if r.ID == id && visible(c, *r) {
			return *r, nil
		}
	}
	return note{}, ontology.ErrNotFound
}

func (n *notes) create(c module.Caller, title, body string, shared bool) string {
	n.mu.Lock()
	defer n.mu.Unlock()
	id := fmt.Sprintf("n_%d", time.Now().UnixNano())
	n.tenants[c.TenantID] = append(n.tenant(c.TenantID), &note{ID: id, Title: title, Body: body, State: "open", Author: c.UserID, Shared: shared, Revision: 1, Updated: time.Now().UTC()})
	return id
}

// update changes one note at the revision the caller read, as a module's command does in one
// transaction.
func (n *notes) update(c module.Caller, id string, revision int64, change func(*note)) error {
	n.mu.Lock()
	defer n.mu.Unlock()
	for _, r := range n.tenant(c.TenantID) {
		if r.ID != id {
			continue
		}
		if revision != r.Revision {
			return ontology.ErrStaleRevision
		}
		change(r)
		r.Revision++
		r.Updated = time.Now().UTC()
		return nil
	}
	return ontology.ErrNotFound
}
