<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)"  srcset="./assets/neofetch-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./assets/neofetch-light.svg">
  <img alt="Mark Jordan Javier — full stack web developer, Batangas, Philippines" src="./assets/neofetch-dark.svg" width="850">
</picture>

<br/>

[**jordiee.me**](https://jordiee.me) · [LinkedIn](https://www.linkedin.com/in/mark-jordan-javier-29b72935a/) · [Email](mailto:javiermarkjordan@gmail.com) · [Book a call](https://calendly.com/javiermarkjordan/30min)

</div>

---

## About this repo

Source for [jordiee.me](https://jordiee.me) — a single-page portfolio built with React 19 and Vite. Sections cover profile, experience, education and projects, and certifications, with a client-side ASCII rendering of the portrait above.

**Stack**

| Layer | What's used |
| --- | --- |
| Framework | React 19, Vite 7 |
| Styling | Tailwind CSS v4 (`@tailwindcss/vite`) |
| Motion | Framer Motion |
| 3D | Three.js via `@react-three/fiber` + `drei` |
| Icons | `lucide-react`, `react-icons` |
| Images | `sharp` (WebP conversion) |
| Lint | ESLint 9 flat config |

## Running locally

```bash
npm install
npm run dev        # vite dev server
npm run build      # production build to dist/
npm run preview    # serve the production build
npm run lint       # eslint
```

Source images are committed as PNG/JPEG and converted to WebP by `convert_images.js`:

```bash
node convert_images.js
```

## Layout

```
src/
├── App.jsx                    entry composition
├── About.jsx                  profile + tech stack
├── Job.jsx                    experience
├── Education.jsx              education + projects
├── Certificate.jsx            certifications
├── components/
│   ├── AsciiPortrait.jsx      canvas → ASCII, rendered client-side
│   ├── ScrollCanvas.jsx       scroll-driven background
│   ├── TechLogoMarquee.jsx    animated logo strip
│   ├── TiltCard.jsx           pointer-tilt card wrapper
│   ├── NavBar.jsx  Footer.jsx  DarkModeToggle.jsx
│   └── ...
├── context/DarkModeContext.jsx
└── assets/                    portrait, certificates, project shots
```

## The card at the top

The banner is a generated SVG, not a code block — fenced code can't carry colour on GitHub. Two themes are rendered and swapped by `prefers-color-scheme`.

| File | Purpose |
| --- | --- |
| `.github/assets/portrait.txt` | The ASCII art, as plain text |
| `.github/card-config.json` | All the copy — edit this, not the script |
| `.github/scripts/generate_card.py` | Layout + live GitHub stats → SVG |
| `.github/scripts/make_ascii.py` | Regenerates the ASCII art from a photo |
| `.github/workflows/profile-card.yml` | Daily refresh, commits only on change |

Regenerate by hand:

```bash
pip install pillow numpy
python3 .github/scripts/make_ascii.py src/assets/me/portrait.png   # optional
GH_TOKEN=<token> python3 .github/scripts/generate_card.py
```

Without a token the script falls back to the values cached in `.github/stats-cache.json`, so it always produces a valid card. The workflow uses the built-in `GITHUB_TOKEN` by default, which only sees **public** repositories; add a fine-grained PAT as the `GH_PAT` secret to include private ones.

> Columns are pinned with absolute `x` positions and `textLength` on every run, so the art and the dotted leaders stay aligned regardless of which monospace font the reader's machine substitutes.

---

<div align="center">
<em>"Never stop learning; every day holds something new to discover."</em>
</div>
