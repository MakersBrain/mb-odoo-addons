# French glossary (`fr_FR`)

Authority for French terminology across every addon in this repository. One
English source term maps to exactly one French UI form. An agent that needs a
term not listed here proposes it to the coordinator rather than choosing
silently, and the coordinator adds it below.

English is the source language. It stays in Python, XML, QWeb, JavaScript,
manifests, help text, exceptions, reports, and emails. French lives only in
`addons/<module>/i18n/fr.po`.

## Core business vocabulary

| English source | French | Notes |
|---|---|---|
| consignment, consignment sale | dépôt-vente | The French legal/business expression. Never "consignation". |
| consignor | déposant | The maker who leaves goods on consignment. |
| consignee | dépositaire | The shop holding the goods. The counterpart of déposant. |
| depositary sale report | relevé de ventes du dépositaire | The `mb.depot.sale.report` model. mb_depot owns the wording; every addon that inherits the model uses this exact string. |
| retail price | prix public | The shelf price. Distinct from "pitch price" (prix de vente conseillé). |
| reversal | extourne | Correcting a posted depot report. |
| depot | dépôt | The consignment outlet. Never "entrepôt" — that is a stock warehouse. |
| depot (as a physical shop) | point de vente | Only where the sentence is about the shop as a retail location. |
| warehouse | entrepôt | Native Inventory wording; reserved for `stock.warehouse`. |
| turnover | chiffre d'affaires | Never "profit", never "recettes". |
| customer receipts | encaissements clients | Cash actually collected, VAT included. Distinct from turnover. |
| revenue | produits | Accounting sense. Use "chiffre d'affaires" for sales volume. |
| commercial operation | opération commerciale | The shared planning model. |
| operation (planning record) | opération | Short form once the context is established. |
| refill | réassort | The single approved UI form, and the word native Inventory uses for "Replenishment". Never "réapprovisionnement" in labels or buttons. |
| to refill | réassortir | |
| permanence shift | permanence | Store-attendance obligation. Keep the French word; do not translate as "garde". |
| break-even | seuil de rentabilité | Consistent in fields, reports, and help text. |
| contribution margin | marge sur coûts variables | |
| contribution | contribution | Where the source means the contributed amount, not the margin ratio. |
| baseline | référence | "baseline frozen" -> "référence figée". |
| frozen baseline | référence figée | |
| outcome | résultat | Post-operation actuals. |
| actual (noun) | réalisé | "actual evidence" -> "justificatif du réalisé". |
| forecast | prévision | |
| planned | prévu | |
| comparison window | fenêtre de comparaison | |
| profitability | rentabilité | |
| pitch, pitch price | prix de vente conseillé | Only where the source means a recommended price. |
| stall, market stall | stand | Market-day selling position. |
| market | marché |
| venue | lieu | The place an operation happens. Use "point de vente" only where the sentence is about the shop itself. |
| venue attendance | présence en point de vente | |
| assortment bucket | segment d'assortiment | |
| readiness | état de préparation | |
| shortage | manque | Not "rupture", which implies a stock-out the model does not assert. |
| supply | approvisionnement | |
| snapshot | instantané | |
| outcome pack | dossier de résultat | |
| turnover levies | prélèvements sur le chiffre d'affaires | |
| channel fee | frais de canal | |
| obligation occurrence | occurrence d'obligation | |
| costed | chiffré | An operation whose costs are known. |
| quoted | devisé | A travel estimate that has a price from the provider. Deliberately a different word from "chiffré". | |

## Accounting, tax, and compliance

| English source | French | Notes |
|---|---|---|
| payment receipt | encaissement | Money received. |
| payment | paiement | The transaction. |
| refund | remboursement | Money returned. |
| credit note | avoir | Only the accounting document `account.move` of type refund. |
| filing, declaration | déclaration | Especially URSSAF. |
| to file (a declaration) | déclarer | |
| declaration period | période de déclaration | |
| micro-enterprise | micro-entreprise | |
| flat-rate income tax payment | versement libératoire | Never expand differently. |
| social contributions | cotisations sociales | |
| contribution rate | taux de cotisation | |
| VAT | TVA | |
| VAT excluded | HT | "hors taxes" in prose, "HT" in column headers and short labels. |
| VAT included | TTC | "toutes taxes comprises" in prose, "TTC" in short labels. |
| VAT exemption | franchise en base de TVA | The Article 293 B regime. |
| chamber of trades | chambre de métiers | |
| chamber fee | taxe pour frais de chambre | |
| invoice | facture | |
| invoice line | ligne de facture | |
| statement | relevé | Depot statements. |
| settlement | règlement | Paying the consignor. |
| due date | date d'échéance | |
| tax base | assiette | |
| turnover threshold | seuil de chiffre d'affaires | |
| chamber of commerce | chambre de commerce | |
| receipt book | livre des recettes | The statutory micro-enterprise register. |
| recognition date | date de constatation | When a receipt is recognised, not when it was paid. |
| turnover box | case de chiffre d'affaires | A numbered box on the URSSAF form. |
| annual evidence | justificatifs annuels | |
| craftsperson | artisan | English source is "Craftsperson", never the French word. |
| hosted checkout | paiement hébergé | A payment page hosted by the provider. |
| sole trader | entrepreneur individuel | The statutory legal form. English source spells it "Sole trader (entrepreneur individuel)" so the French rendering is not an identical entry. |
| accounting administrator | administrateur de comptabilité | The role attesting a reconciliation. |

Never translate, never inflect: `URSSAF`, `ACRE`, `CFP`, `CMA`, `SIRET`, `SIREN`,
`APE`, `NAF`, `SumUp`, `TollQuote`, `QR`, `SKU`, `EAN`, `GTIN`, `POS`, `API`,
`CSV`, `PDF`, `ZPL`, `TSPL`, `Article 293 B`, `Article 293 B du CGI`, product
names, and brand names.

Article 293 B statements are legal text. Translate them only to the exact
official French wording — "TVA non applicable, article 293 B du CGI" — and never
paraphrase.

## Ceramics and workshop

| English source | French | Notes |
|---|---|---|
| firing | cuisson | The process. |
| to fire | cuire | |
| firing load | charge de cuisson | The physical kiln load. Never an accounting charge. |
| firing program | programme de cuisson | |
| segment (firing) | palier | A ramp/hold step of a program. |
| ramp | montée | |
| hold, soak | palier de maintien | |
| kiln | four | |
| kiln shelf | plaque d'enfournement | |
| to load the kiln | enfourner | |
| to unload the kiln | défourner | |
| bisque | biscuit | The ceramics stage and the resulting ware. |
| bisque firing | cuisson biscuit | |
| glaze | émail | The material. |
| glazing | émaillage | The stage. |
| glaze firing | cuisson d'émail | |
| greenware | cru | Unfired ware. |
| leather-hard | dur comme du cuir | |
| throwing | tournage | |
| trimming | tournassage | |
| piece | pièce | A single ceramic object. Never confuse with a stock lot. |
| batch | série | A group of pieces made together. |
| loss, breakage | perte | Pieces lost in the process. |
| scrap | rebut | |
| clay body | terre | |
| workshop | atelier | |
| maker, artisan | artisan | |
| studio session | séance d'atelier | |

## Stock, labels, and capture

| English source | French | Notes |
|---|---|---|
| lot | lot | Native Inventory wording. |
| serial number | numéro de série | Native Inventory wording. |
| stock capture | capture de stock | Image-assisted inventory intake. |
| invoice capture | capture de facture | Document intake, not invoice creation. |
| capture | capture | The intake action. |
| to scan | scanner | |
| scanner | scanner | The device or the on-screen reader. |
| barcode | code-barres | |
| label | étiquette | The printed label. |
| label template | modèle d'étiquette | |
| Label Studio | Label Studio | Product name; never translated. |
| printer | imprimante | |
| dpi | ppp | Points par pouce. Native Odoo renders "Output DPI" as "Résolution en ppp", so "ppp" is the house form. |
| firing segment | palier | See the ceramics section; "ramp" and "hold" inside segment help text are "montée" and "maintien". |
| print job | impression | |
| torch, flash (camera) | torche | Camera light on a scanner screen. |
| draft (capture) | brouillon | |
| review | révision | The human check step. |
| to confirm | confirmer | |
| discard | annuler | |
| catalogue | catalogue | |
| product lookup | recherche de produit | |
| provider | fournisseur | An external service provider. Where the source means a supplier of goods, also "fournisseur" — Odoo native. |
| gateway | passerelle | |
| bridge | passerelle | Same word; the addon names stay English. |

## UI chrome conventions

- Buttons and menu items use the infinitive: "Confirm" -> "Confirmer",
  "Create Invoice" -> "Créer la facture".
- Field labels are noun phrases with no trailing colon and no final period.
- Help text and tooltips are full sentences ending with a period.
- Error and warning messages are full sentences ending with a period, addressing
  the user with "vous", never "tu".
- Never use the imperative "Veuillez" chain twice in one message; state the
  problem, then the action.
- Keep the source's capitalisation intent, not its exact case: English Title
  Case becomes French sentence case ("Firing Load" -> "Charge de cuisson").
- Use the typographic apostrophe `'` only where the source uses one; otherwise
  use the straight apostrophe `'` consistently within a catalogue. This
  repository uses the straight apostrophe.
- Use a non-breaking space before `:`, `;`, `!`, `?`, `%`, and inside `« »` only
  when the surrounding catalogue already does; do not introduce U+00A0 into
  short labels where it would break search.

## One English term, more than one French term

Odoo namespaces code translations by module and stores model terms per record, so
the same msgid may legitimately differ between addons when the concept differs.
That is not licence to diverge: the coordinator reconciled every cross-addon
difference at integration, and these are the ones that survived, each with the
reason it is not an inconsistency.

| English | French | Where, and why it differs |
|---|---|---|
| Current | période courante | The current column of the URSSAF declaration report. |
| Current | en cours | A ceramics board item being worked on now. |
| Current | en vigueur | The report snapshot in force. |
| Supply | alimentation | A kiln's power supply, grouped with heating method and kW. |
| Supply | approvisionnement | Restocking, in the commercial stock report. |
| Complete | terminer | A button. Buttons take the infinitive. |
| Complete | terminée | A finished state. States agree with their subject. |

Everything else that differed was reconciled to one term: "Depositary sale
report" to *relevé de ventes du dépositaire*, "Filed" to *déposé* (the verb used
for filing a declaration), "Duration Hours" to *durée (heures)*, "Confidence" to
*confiance*, and "Upload image" to *téléverser une image*.

On *téléverser*: native Odoo French renders "Upload" as "charger" and "télécharger"
interchangeably, which conflates upload with download. This repository uses
*téléverser* for upload, consistently, because the ambiguity is a real usability
problem on a screen that does both.

## Placeholders

Placeholders are code, not prose. `%(product)s`, `%s`, `%d`, `{count}`, and
`{{ value }}` keep their exact spelling and count. Reorder them freely inside the
French sentence only when they are named; positional `%s` must stay in source
order.

## What is never translated

Protocol commands, printer opcodes, barcode payloads, diagnostic and error
codes, log messages, XML IDs, external IDs, database names, field technical
names, domains, API endpoints, HTTP methods, JSON keys, SKU values, AI provider
identifiers, model identifiers, file paths, and URLs.
