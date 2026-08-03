# 0002 — product lookup indexes and supplier extraction

Independent second reference for SC-11. Where solution A declares indexes in the module,
this one specifies them as a migration document with shell-style commands, so a
discriminator pinned to solution A's Python constant fails here.

Run against the catalogue database:

```js
db.products.createIndex({ category: 1 });
db.products.createIndex({ active: 1, price: 1 });
db.suppliers.createIndex({ supplier_id: 1 }, { unique: true });
```

Supplier records move out of each product document into a `suppliers` collection; products
keep only `supplier_id`, so a supplier detail is stored once rather than per product.
