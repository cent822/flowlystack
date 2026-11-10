// The slides of Documents mode: the same registry shape as slides.js, drawn by the same chart modules.
// Shape, Vocabulary, Structure, Repeats, Craft and Use. `min: true` = the cards that need a crowd:
// the number is the snapshot's own `min_card` (one place, backend/gallery_docs.py), not a constant here.
import { cloud } from "./charts/cloud.js";
import { network } from "./charts/network.js";
import { arcs } from "./charts/arcs.js";
import { map } from "./charts/map.js";
import { pack } from "./charts/pack.js";
import { dendro } from "./charts/dendro.js";
import { repeats } from "./charts/repeats.js";
import { added } from "./charts/added.js";
import { treemap } from "./charts/treemap.js";
import { lengths } from "./charts/lengths.js";
import { pcp } from "./charts/pcp.js";
import { corr } from "./charts/corr.js";
import { flow } from "./charts/flow.js";
import { unused } from "./charts/unused.js";
import { nearest } from "./charts/nearest.js";

export const SLIDES_DOCS = [
  { id: "shape", fit: true, title: "Shape", how: "What your collection is made of. Drag across the columns to pick a time range.", cards: [
    { key: "added", title: "When you added them", caption: "One column per day (per month for a long history), coloured by topic group. This is the day a file was imported, not when it was written, so a bulk import is one tall column. Click a colour to focus.", span: 12, draw: added },
    { key: "tree", title: "What is in it", caption: "Each tile is a file type, split by the collection a document is in; area is words (a document in two collections is counted once). Click a file type to filter by it.", span: 7, draw: treemap },
    { key: "len", title: "How big", caption: "Documents by length in words, on a log scale; pale columns are all documents, bright ones match your filters. Click a column to select those documents.", span: 5, draw: lengths }] },
  { id: "vocabulary", fit: true, title: "Vocabulary", how: "What your documents are about. Click a word to see only the documents that use it.", cards: [
    { key: "cloud", title: "Your words", caption: "Bigger words are in more documents, so one very long file cannot dominate. Settings > Knowledge lets you add words to ignore.", span: 6, draw: cloud },
    { key: "net", title: "Words that go together", caption: "Words joined by a line often appear in the same document. Click a word to filter by it.", span: 6, min: true, draw: network },
    { key: "arcs", title: "Phrases that come back", caption: "An arc joins two words that are often written next to each other; thicker means in more documents. Click an arc.", span: 12, min: true, draw: arcs }] },
  { id: "structure", fit: true, title: "Structure", how: "How your documents group by meaning. Drag a box on the map to select; click a bubble to focus a group.", cards: [
    { key: "map", title: "Map of your documents", caption: "Each dot is a document. Dots close together say similar things; rings show where they crowd. Switch to Passages to see what is inside the documents: one dot for each passage, from the stored embeddings.", span: 7, min: true, seg: "Type", view: true, draw: map },
    { key: "pack", title: "Topics and their words", caption: "Each large bubble is a group of similar documents; the small bubbles inside are its words.", span: 5, min: true, draw: pack },
    { key: "dendro", title: "Which topics are close", caption: "Groups that join early are the most alike.", span: 12, min: true, draw: dendro }] },
  { id: "repeats", fit: true, title: "Repeats", how: "What you keep twice. Documents that say nearly the same thing are often old versions or copies.", cards: [
    { key: "repeats", title: "The same text, kept twice", caption: "Each dot is a document on the day you added it; an arc joins two similar ones. Exact copies cannot exist (the same file is stored once), so these are near-copies. Click an arc to select the group.", span: 12, min: true, draw: repeats }] },
  { id: "craft", fit: true, title: "Craft", how: "How your documents differ in make-up. Drag on an axis to select, for example long documents full of numbers.", cards: [
    { key: "pcp", title: "Make-up of each document", caption: "Each line is a document across six measurements, coloured by file type (by topic group when all are one type). Brush an axis to select. The numbers on an axis are real values; the top of each axis is the 99th percentile. Words are counted from the passages, so they are about right.", span: 7, min: true, draw: pcp },
    { key: "corr", title: "How the measurements relate", caption: "Dots show two measurements against each other; the curve on the diagonal shows how common each value is.", span: 5, min: true, draw: corr }] },
  { id: "use", fit: true, title: "Use", how: "Which documents earn their place. Counted from the conversations you saved in Collections; nothing is read from anywhere else.", cards: [
    { key: "flow", title: "From file type to cited", caption: "Each flow is documents of one file type in one collection, and whether a saved chat ever cited them. Thin flows are drawn wider so they stay visible. Click a box to select its documents.", span: 12, draw: flow },
    { key: "unused", title: "Never cited, and most cited", caption: "Documents no saved chat has used, newest first, and the ones used most. A document counts when a passage of it was sent to the model and cited. Click a row to select it.", span: 7, draw: unused },
    { key: "near", title: "Closest Library prompts", caption: "For one selected document: the prompts in your Library closest to it in meaning, from the stored embeddings. Needs an embedding model.", span: 5, draw: nearest }] },
];
