# Forensic checklist for a deep dive (spec §8.2)

Propose a fact only with its accession and a verbatim quote that contains its number; Python drops
anything it cannot find in the filing. Look for: one-off items (asset sales, tax benefits,
restructuring and legal charges), segment revenue, guidance ranges and any cut, backlog, customer
concentration and any lost customer, covenant terms, share-class counts. Units: `USD`,
`USD_thousands`, `USD_millions`, `USD_billions`, `pct`, `count`. Name a canonical XBRL item
(`revenue`, `sbc`, ...) only when the figure is one; Python then checks it against companyfacts.
