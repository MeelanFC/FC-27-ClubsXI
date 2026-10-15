# The flat card design

The Squad page shows the eleven as flat cards on a dark green pitch. This file
gives the design rules, the HTML of one card and the CSS. Code: `hero()` and
`AB_CSS` in `src/clubsxi/picker.py`.

## 1. Design rules

1. The whole eleven fits on one screen, on a phone and on a desktop. Card
   height follows the window height.
2. Four rows, top to bottom: ATK (3 cards), MID (3), DEF (4), GK (1).
3. The back four always stays on one row. Rows never wrap.
4. Each card has three parts:
   - a blue bar with the position and the rating,
   - the starter, large, with the build below the name,
   - up to two backups in thin rows (silver, then bronze).
5. The tier shows as a coloured left edge: gold, silver, bronze. No gradients
   and no images on the card.
6. An empty spot shows "AI" in grey with "no one free".
7. Long names cut with "..." and never push the card wider.
8. All text has a contrast of 5:1 or better on its background.
9. "How this works" is a fold-out (`<details>`), closed by default.

Colours:

| Token | Value | Use |
|---|---|---|
| `--blue` | `#2F5BB7` | Card bar. Change it to your club colour. |
| `--gold` | `#f2c94c` | Starter edge, rating badge |
| `--silver` | `#c9d1dc` | First backup edge |
| `--bronze` | `#d08a4a` | Second backup edge |
| card body | `#141a26` | Card background |
| backup row | `#1b2333` | Backup background |
| pitch | `#0f2a1c` / `#11301f` | Stripes, 8 bands |

## 2. HTML of one card

```html
<div class="xc">
  <div class="xh"><span>ST</span><span class="rt">7.2</span></div>
  <div class="gold">
    <div class="gn" title="PlayerName">PlayerName</div>
    <div class="gb">Finisher</div>
  </div>
  <div class="sv" title="Target"><b>BackupOne</b><em>Target · 6.8</em></div>
  <div class="sv bz" title="Magician"><b>BackupTwo</b><em>Magician · 6.1</em></div>
</div>
```

An AI card adds the class `ai` and shows `AI` and `no one free`.

A row is `<div class="row">` with the cards inside. The pitch is
`<div class="pitch">` with the four rows inside. Everything sits in
`<div class="pk">`.

## 3. The CSS

```css
.pk{--blue:#2F5BB7;--gold:#f2c94c;--silver:#c9d1dc;--bronze:#d08a4a}
.pk .pitch{display:grid;gap:clamp(6px,1.4vh,14px);margin-top:6px;
 padding:clamp(8px,1.6vh,16px) 8px;border-radius:14px;
 background:repeating-linear-gradient(180deg,#0f2a1c 0 12.5%,#11301f 12.5% 25%);
 border:1px solid #1f4a33}
.pk .row{display:flex;justify-content:center;flex-wrap:nowrap;gap:clamp(6px,1vw,12px);margin:0}
.pk .xc{flex:none;width:min(230px,calc((100vw - 80px) / 4));height:calc((100dvh - 190px) / 4);
 min-height:96px;max-height:150px;display:flex;flex-direction:column;background:#141a26;
 border:1px solid #2a3550;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.35)}
.pk .xc .xh{display:flex;justify-content:space-between;align-items:center;background:var(--blue);
 color:#fff;padding:2px 10px;font-size:clamp(11px,1.5vh,14px);font-weight:800;letter-spacing:.06em}
.pk .xc .xh .rt{background:var(--gold);color:#1a1300;border-radius:6px;padding:0 6px;
 font-size:clamp(12px,1.7vh,16px)}
.pk .xc .gold{flex:1;display:flex;flex-direction:column;justify-content:center;padding:2px 10px;
 border-left:4px solid var(--gold);min-height:0}
.pk .xc .gn{color:#fff;font-weight:800;font-size:clamp(13px,2.1vh,19px);line-height:1.15;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pk .xc .gb{color:#aab6cc;font-size:clamp(10px,1.4vh,13px);white-space:nowrap;overflow:hidden;
 text-overflow:ellipsis}
.pk .xc .sv{display:flex;gap:6px;align-items:center;padding:3px 10px;background:#1b2333;
 border-top:1px solid #2a3550;border-left:4px solid var(--silver);color:#dfe5ee;
 font-size:clamp(11px,1.6vh,14px);min-width:0}
.pk .xc .sv b{flex:0 1 auto;min-width:55%;font-weight:700;white-space:nowrap;overflow:hidden;
 text-overflow:ellipsis}
.pk .xc .sv em{flex:1 1 0;min-width:0;text-align:right;font-style:normal;color:#aab6cc;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pk .xc .sv.bz{border-left-color:var(--bronze)}
.pk .xc.ai .gn{color:#8d98ad}
```

How the sizes work:

- Width: four cards and their gaps fit the screen width
  (`(100vw - 80px) / 4`), with a maximum of 230 px.
- Height: four rows fit the screen height (`(100dvh - 190px) / 4`). The 190 px
  is the page header and the toggle. The height stays between 96 and 150 px.
- Font sizes use `clamp()` with `vh`, so text shrinks with the card.

## 4. The version toggle without JavaScript

Two hidden radio buttons and two labels switch between version A and B.

```html
<input type="radio" name="ab" id="ab-b" checked>
<input type="radio" name="ab" id="ab-a">
<div class="abbar"><label for="ab-b">B: captain's rules</label><label for="ab-a">A: by the numbers</label></div>
<div class="abb">... version B pitch ...</div>
<div class="aba">... version A pitch ...</div>
```

```css
.pk input[name=ab]{display:none}
.pk .abbar{display:flex;gap:8px;margin:10px 0}
.pk .abbar label{border:1px solid var(--line);border-radius:16px;padding:5px 14px;cursor:pointer;font-size:13px}
.pk #ab-a:checked~.abbar label[for=ab-a],.pk #ab-b:checked~.abbar label[for=ab-b]{
 background:var(--accent);color:#000;border-color:var(--accent);font-weight:700}
.pk .aba,.pk .abb{display:none}
.pk #ab-a:checked~.aba,.pk #ab-b:checked~.abb{display:block}
```

## 5. Optional card art (Cards page only)

The older `/cards` page can show an image behind each card. No image is
included, because card art from the game is EA's property. To add your own:

1. Make a PNG of about 900 x 1260 pixels.
2. Save it as `src/clubsxi/assets/card.png`.
3. Restart the viewer.

Without the image, the cards show with no picture behind them.
