# WorkTimer Design System

## Theme

Тёмная «цифровая мастерская» для работы и стримов в вечернем освещении. Поверхности матовые и глубокие, без стеклянных карточек и декоративного свечения.

## Color strategy

Restrained product palette: холодные сине-графитовые нейтрали и электрический голубой только для активного состояния. Семантические цвета фаз применяются в индикаторах, прогрессе и статусах, но не заменяют текст.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#07111c` | Page background |
| `--surface` | `#0c1a29` | Navigation and panels |
| `--surface-raised` | `#102337` | Controls and selected rows |
| `--line` | `#203a52` | Borders and tracks |
| `--text` | `#eaf2f8` | Primary text |
| `--muted` | `#93a9bc` | Secondary text |
| `--accent` | `#22c7ff` | Primary action and active state |
| `--work` | `#22c7ff` | Work phase |
| `--rest` | `#56d6a0` | Rest phase |
| `--prep` | `#9b8cff` | Preparation phase |
| `--warning` | `#e7b35a` | Attention state |
| `--danger` | `#ef7070` | Destructive state |

## Typography

Use `Inter, "Segoe UI", system-ui, sans-serif` for the product UI. Timer digits use `"IBM Plex Mono", "Cascadia Mono", Consolas, monospace` with tabular figures. Type scale: 12, 14, 16, 20, 28, 64 px.

## Components

- 8 px spacing rhythm, with 12/20/32 px breaks for hierarchy.
- Controls have a 10 px radius, visible 2 px focus ring and 160 ms state transitions.
- Primary action is solid cyan; secondary actions are outlined or quiet.
- Scenario phases are dense rows, not independent cards.
- Empty states teach the next action in one sentence.

## Layout

Desktop: fixed 232 px navigation rail, fluid working canvas. Mobile/narrow: top navigation and single column. The current timer owns the center; secondary context stays to the side or below.

## Motion

Only state feedback: progress transitions, selection and loading. Respect `prefers-reduced-motion` and avoid layout animation.
