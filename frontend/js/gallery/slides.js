// `fit: true` = the page holds still in the window and only this slide's cards scroll (wide windows; so far only Pulse, trial).
// The registry: a slide is {id, title, how, cards}; a card is {key, title, caption, span, draw(el)}.
// `min` = fewest prompts the chart needs (below it the card says so). A card without `draw` shows a "built in a later step" note. Adding a question = one chart module + one card here (+ its snapshot field).
import { calendar } from "./charts/calendar.js";
import { stream } from "./charts/stream.js";
import { ridge } from "./charts/ridge.js";
import { cloud } from "./charts/cloud.js";
import { network } from "./charts/network.js";
import { arcs } from "./charts/arcs.js";
import { map } from "./charts/map.js";
import { pack } from "./charts/pack.js";
import { dendro } from "./charts/dendro.js";
import { repeats } from "./charts/repeats.js";
import { pcp } from "./charts/pcp.js";
import { corr } from "./charts/corr.js";
import { sankey } from "./charts/sankey.js";
import { treemap } from "./charts/treemap.js";
import { versions } from "./charts/versions.js";

export const SLIDES = [
  { id: "pulse", fit: true, title: "Pulse", how: "When and how you work. Drag across the calendar or the streamgraph to pick a time range.", cards: [
    { key: "cal", title: "Days you prompted", caption: "Each square is a day; darker means more prompts.", span: 12, draw: calendar },
    { key: "stream", title: "Topics over time", caption: "Each colour is a group of similar prompts; thicker means more of them that month. Click a colour to focus.", span: 7, draw: stream },
    { key: "ridge", title: "Time of day, per agent", caption: "Higher means more prompts at that hour. Click a ridge to filter by agent.", span: 5, draw: ridge }] },
  { id: "vocabulary", fit: true, title: "Vocabulary", how: "What you write about. Click a word to see only the prompts that use it.", cards: [
    { key: "cloud", title: "Your words", caption: "Bigger words are in more prompts. Greetings and filler are left out; Settings > Knowledge lets you add your own words to ignore.", span: 6, draw: cloud },
    { key: "net", title: "Words that go together", caption: "Words joined by a line often appear in the same prompt. Click a word to filter by it.", span: 6, min: 50, draw: network },
    { key: "arcs", title: "Phrases you repeat", caption: "An arc joins two words you keep writing next to each other; thicker means more often. Click an arc.", span: 12, min: 50, draw: arcs }] },
  { id: "structure", fit: true, title: "Structure", how: "How your prompts group by meaning. Drag a box on the map to select; click a bubble to focus a group.", cards: [
    { key: "map", title: "Map of your prompts", caption: "Each dot is a prompt. Dots close together say similar things; rings show where they crowd.", span: 7, min: 50, seg: true, draw: map },
    { key: "pack", title: "Topics and their words", caption: "Each large bubble is a group of similar prompts; the small bubbles inside are its words.", span: 5, min: 50, draw: pack },
    { key: "dendro", title: "Which topics are close", caption: "Groups that join early are the most alike.", span: 12, min: 50, draw: dendro }] },
  { id: "repeats", fit: true, title: "Repeats", how: "What you rewrite. Prompts that say nearly the same thing are good candidates for one template.", cards: [
    { key: "repeats", title: "The same idea, written again", caption: "Each arc joins two similar prompts; a long arc means you came back to it months later. Click an arc to select the group.", span: 12, min: 50, draw: repeats }] },
  { id: "craft", fit: true, title: "Craft", how: "How your prompts differ in style. Drag on an axis to select, for example long prompts with code.", cards: [
    { key: "pcp", title: "Style of each prompt", caption: "Each line is a prompt across six measurements. Brush an axis to select. The numbers on an axis are real values; the top of a count axis is the 99th percentile.", span: 7, min: 50, draw: pcp },
    { key: "corr", title: "How the measurements relate", caption: "Dots show two measurements against each other; the curve on the diagonal shows how common each value is.", span: 5, min: 50, draw: corr }] },
  { id: "lifecycle", fit: true, title: "Lifecycle", how: "Which prompts grow up. Most are never touched after capture; this shows where the ones that are go.", cards: [
    { key: "sankey", title: "From capture to Studio", caption: "Thin flows are drawn at a minimum width so they stay visible. Click a Library group to select it.", span: 12, draw: sankey },
    { key: "tree", title: "Where prompts live", caption: "Each tile is a project or model, grouped by agent. Click an agent to filter by it.", span: 7, draw: treemap },
    { key: "versions", title: "Version history (Studio)", caption: "Each dot is a saved version of one Studio prompt.", span: 5, draw: versions }] },
];
export const slideIndex = (id) => Math.max(0, SLIDES.findIndex((s) => s.id === id));
