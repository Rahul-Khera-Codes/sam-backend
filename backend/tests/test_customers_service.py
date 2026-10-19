from app.services.customers_service import resolve_or_create_customer


class _Q:
    def __init__(self, db, name):
        self.db, self.name, self.f, self.ilike_f, self.op = db, name, [], None, None

    def select(self, *_): return self
    def eq(self, c, v): self.f.append((c, v)); return self
    def is_(self, c, v): self.f.append((c, None)); return self
    def ilike(self, c, v): self.ilike_f = (c, v.lower()); return self
    def insert(self, row): self.op = row; return self

    def execute(self):
        rows = self.db.rows
        if self.op is not None:
            r = {**self.op, "id": f"c{len(rows)+1}"}
            rows.append(r)
            return type("R", (), {"data": [r]})
        out = [r for r in rows if all(r.get(c) == v for c, v in self.f)]
        if self.ilike_f:
            c, v = self.ilike_f
            out = [r for r in out if (r.get(c) or "").lower() == v]
        return type("R", (), {"data": out})


class _DB:
    def __init__(self): self.rows = []
    def table(self, n): return _Q(self, n)


def _call(db, name, phone=None, email=None):
    return resolve_or_create_customer(db, "b1", None, name, phone, email)


def test_same_person_reuses_customer():
    db = _DB()
    a = _call(db, "Jane Doe", "780-994-4331")
    assert _call(db, "jane doe", "(780) 994 4331") == a
    assert len(db.rows) == 1


def test_different_name_same_phone_creates_new_customer():
    db = _DB()
    a = _call(db, "Greg Bitz", "7809944331")
    b = _call(db, "Noshow Test", "7809944331")
    assert a != b and len(db.rows) == 2


def test_name_only_creates_and_reuses():
    db = _DB()
    a = _call(db, "Walk In")
    assert a and _call(db, "Walk In") == a and len(db.rows) == 1
    assert _call(db, "Other Person") != a


def test_name_only_does_not_attach_to_customer_with_contact_info():
    db = _DB()
    a = _call(db, "Jane Doe", "7809944331")
    assert _call(db, "Jane Doe") != a


def test_blank_name_returns_none():
    assert _call(_DB(), "  ") is None
