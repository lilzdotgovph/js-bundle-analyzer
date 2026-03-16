#!/usr/bin/env python3
"""
Webpack .js Bundle Scanner
Directly fetches a webpack .js bundle URL and detects all embedded
JavaScript libraries, components, and frameworks with their versions.

Usage:
    python webpack_scanner.py <bundle_url>
    python webpack_scanner.py https://example.com/static/js/main.abc123.js
"""

import re
import sys
import requests
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# DETECTION STRATEGIES
#
# For each library we use multiple regex patterns, ordered from most-specific
# (gives a real version) to least-specific (signals presence only).
#
# Webpack bundles encode package metadata in several ways:
#   1. Inline version strings:  React.version="18.2.0"
#   2. Module map strings:      "react","18.2.0"  or  "react":"18.2.0"
#   3. npm package refs:        react@18.2.0  or  react-18.2.0
#   4. CDN path segments:       /react-18.2.0.min.js
#   5. Runtime constants:       __REACT_VERSION__="18.2.0"
#   6. Presence-only markers:   __webpack_require__, webpackJsonp, etc.
# ─────────────────────────────────────────────────────────────────────────────

LIBRARY_PATTERNS = [

    # ══════════════════════════════════════════════════════════════════════════
    # CORE FRAMEWORKS
    # ══════════════════════════════════════════════════════════════════════════

    ("React", [
        r'React\.version\s*[=:]\s*["\']([0-9][^"\']{1,20})["\']',
        r'__REACT_VERSION__\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"react"\s*,\s*"([0-9][^"]{1,20})"',
        r"'react'\s*,\s*'([0-9][^']{1,20})'",
        r'"react"\s*:\s*"([0-9][^"]{1,20})"',
        r'react(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'/react[.\-]([0-9][^/\s"\']{1,20})(?:\.min)?\.js',
        r'createElement\s*,\s*["\']react["\']',
        r'__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED',
    ]),

    ("React DOM", [
        r'"react-dom"\s*,\s*"([0-9][^"]{1,20})"',
        r'"react-dom"\s*:\s*"([0-9][^"]{1,20})"',
        r'react-dom(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'/react-dom[.\-]([0-9][^/\s"\']{1,20})(?:\.min)?\.js',
        r'ReactDOM\.render|createRoot\s*\(',
    ]),

    ("Vue.js", [
        r'Vue\.version\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"vue"\s*,\s*"([0-9][^"]{1,20})"',
        r'"vue"\s*:\s*"([0-9][^"]{1,20})"',
        r'vue(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'/vue[.\-]([0-9][^/\s"\']{1,20})(?:\.min)?\.js',
        r'__VUE_OPTIONS_API__|__VUE_PROD_DEVTOOLS__',
    ]),

    ("Angular", [
        r'"@angular/core"\s*:\s*"([0-9][^"]{1,20})"',
        r'"@angular/core"\s*,\s*"([0-9][^"]{1,20})"',
        r'@angular/core(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'platformBrowser|NgModule|definitelyTyped|defineComponent',
    ]),

    ("AngularJS", [
        r'angular\.version\.full\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"angular"\s*:\s*"([0-9][^"]{1,20})"',
        r'angular(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'angular\.module\s*\(',
    ]),

    ("Svelte", [
        r'"svelte"\s*,\s*"([0-9][^"]{1,20})"',
        r'"svelte"\s*:\s*"([0-9][^"]{1,20})"',
        r'svelte(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'SvelteComponent|SvelteComponentDev|__svelte_',
    ]),

    ("Solid.js", [
        r'"solid-js"\s*,\s*"([0-9][^"]{1,20})"',
        r'"solid-js"\s*:\s*"([0-9][^"]{1,20})"',
        r'solid-js(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'createSignal|createEffect|createMemo',
    ]),

    ("Preact", [
        r'"preact"\s*,\s*"([0-9][^"]{1,20})"',
        r'"preact"\s*:\s*"([0-9][^"]{1,20})"',
        r'preact(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'preactRender|h\s*=\s*preact\.h',
    ]),

    ("Ember.js", [
        r'Ember\.VERSION\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"ember"\s*:\s*"([0-9][^"]{1,20})"',
        r'ember(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'Ember\.Application\.create',
    ]),

    ("Backbone.js", [
        r'Backbone\.VERSION\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"backbone"\s*:\s*"([0-9][^"]{1,20})"',
        r'backbone(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # META-FRAMEWORKS
    # ══════════════════════════════════════════════════════════════════════════

    ("Next.js", [
        r'"next"\s*,\s*"([0-9][^"]{1,20})"',
        r'"next"\s*:\s*"([0-9][^"]{1,20})"',
        r'next(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'__NEXT_DATA__|__nextjs_|/_next/static/',
    ]),

    ("Nuxt.js", [
        r'"nuxt"\s*,\s*"([0-9][^"]{1,20})"',
        r'"nuxt"\s*:\s*"([0-9][^"]{1,20})"',
        r'nuxt(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'__NUXT__|__nuxt_',
    ]),

    ("Gatsby", [
        r'"gatsby"\s*,\s*"([0-9][^"]{1,20})"',
        r'"gatsby"\s*:\s*"([0-9][^"]{1,20})"',
        r'gatsby(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'___gatsby|gatsby-browser',
    ]),

    ("Remix", [
        r'"@remix-run/react"\s*:\s*"([0-9][^"]{1,20})"',
        r'@remix-run/react(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'__remixContext|RemixBrowser',
    ]),

    ("Astro", [
        r'"astro"\s*:\s*"([0-9][^"]{1,20})"',
        r'astro(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'astro-island|astro:scripts',
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # UI / COMPONENT LIBRARIES
    # ══════════════════════════════════════════════════════════════════════════

    ("Bootstrap", [
        r'Bootstrap\.VERSION\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"bootstrap"\s*,\s*"([0-9][^"]{1,20})"',
        r'"bootstrap"\s*:\s*"([0-9][^"]{1,20})"',
        r'bootstrap(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'/bootstrap[.\-]([0-9][^/\s"\']{1,20})(?:\.min)?\.(?:js|css)',
    ]),

    ("Tailwind CSS", [
        r'"tailwindcss"\s*:\s*"([0-9][^"]{1,20})"',
        r'tailwindcss(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'tailwind\.config',
    ]),

    ("Material UI (MUI)", [
        r'"@mui/material"\s*:\s*"([0-9][^"]{1,20})"',
        r'@mui/material(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'"@material-ui/core"\s*:\s*"([0-9][^"]{1,20})"',
    ]),

    ("Ant Design", [
        r'"antd"\s*,\s*"([0-9][^"]{1,20})"',
        r'"antd"\s*:\s*"([0-9][^"]{1,20})"',
        r'antd(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Chakra UI", [
        r'"@chakra-ui/react"\s*:\s*"([0-9][^"]{1,20})"',
        r'@chakra-ui/react(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'ChakraProvider|useColorMode',
    ]),

    ("Vuetify", [
        r'"vuetify"\s*,\s*"([0-9][^"]{1,20})"',
        r'"vuetify"\s*:\s*"([0-9][^"]{1,20})"',
        r'vuetify(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("shadcn/ui", [
        r'"@radix-ui/react-dialog"\s*:\s*"([0-9][^"]{1,20})"',
        r'@radix-ui/react-(?:dialog|popover|tooltip|dropdown-menu)',
    ]),

    ("Radix UI", [
        r'"@radix-ui/react-[^"]+"\s*:\s*"([0-9][^"]{1,20})"',
        r'@radix-ui/(?:react|primitive)(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Headless UI", [
        r'"@headlessui/react"\s*:\s*"([0-9][^"]{1,20})"',
        r'@headlessui/react(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("PrimeReact", [
        r'"primereact"\s*:\s*"([0-9][^"]{1,20})"',
        r'primereact(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Mantine", [
        r'"@mantine/core"\s*:\s*"([0-9][^"]{1,20})"',
        r'@mantine/core(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # STATE MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════

    ("Redux", [
        r'"redux"\s*,\s*"([0-9][^"]{1,20})"',
        r'"redux"\s*:\s*"([0-9][^"]{1,20})"',
        r'redux(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'createStore\s*\(|combineReducers\s*\(',
    ]),

    ("Redux Toolkit", [
        r'"@reduxjs/toolkit"\s*:\s*"([0-9][^"]{1,20})"',
        r'@reduxjs/toolkit(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'configureStore\s*\(',
    ]),

    ("React-Redux", [
        r'"react-redux"\s*,\s*"([0-9][^"]{1,20})"',
        r'"react-redux"\s*:\s*"([0-9][^"]{1,20})"',
        r'react-redux(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("MobX", [
        r'"mobx"\s*,\s*"([0-9][^"]{1,20})"',
        r'"mobx"\s*:\s*"([0-9][^"]{1,20})"',
        r'mobx(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'makeObservable|makeAutoObservable',
    ]),

    ("Zustand", [
        r'"zustand"\s*,\s*"([0-9][^"]{1,20})"',
        r'"zustand"\s*:\s*"([0-9][^"]{1,20})"',
        r'zustand(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Recoil", [
        r'"recoil"\s*:\s*"([0-9][^"]{1,20})"',
        r'recoil(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'RecoilRoot|atom\s*\(\s*\{',
    ]),

    ("Jotai", [
        r'"jotai"\s*:\s*"([0-9][^"]{1,20})"',
        r'jotai(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("XState", [
        r'"xstate"\s*:\s*"([0-9][^"]{1,20})"',
        r'xstate(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'createMachine\s*\(',
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # ROUTING
    # ══════════════════════════════════════════════════════════════════════════

    ("React Router", [
        r'"react-router-dom"\s*,\s*"([0-9][^"]{1,20})"',
        r'"react-router"\s*,\s*"([0-9][^"]{1,20})"',
        r'"react-router(?:-dom)?"\s*:\s*"([0-9][^"]{1,20})"',
        r'react-router(?:-dom)?(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'BrowserRouter|createBrowserRouter',
    ]),

    ("Vue Router", [
        r'"vue-router"\s*,\s*"([0-9][^"]{1,20})"',
        r'"vue-router"\s*:\s*"([0-9][^"]{1,20})"',
        r'vue-router(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'createRouter\s*\(',
    ]),

    ("TanStack Router", [
        r'"@tanstack/react-router"\s*:\s*"([0-9][^"]{1,20})"',
        r'@tanstack/react-router(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # DATA FETCHING / API
    # ══════════════════════════════════════════════════════════════════════════

    ("Axios", [
        r'axios\.VERSION\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"axios"\s*,\s*"([0-9][^"]{1,20})"',
        r'"axios"\s*:\s*"([0-9][^"]{1,20})"',
        r'axios(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("TanStack Query", [
        r'"@tanstack/react-query"\s*:\s*"([0-9][^"]{1,20})"',
        r'@tanstack/react-query(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'"react-query"\s*:\s*"([0-9][^"]{1,20})"',
        r'useQuery\s*\(|QueryClient\s*\(',
    ]),

    ("SWR", [
        r'"swr"\s*,\s*"([0-9][^"]{1,20})"',
        r'"swr"\s*:\s*"([0-9][^"]{1,20})"',
        r'swr(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("GraphQL", [
        r'"graphql"\s*,\s*"([0-9][^"]{1,20})"',
        r'"graphql"\s*:\s*"([0-9][^"]{1,20})"',
        r'graphql(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Apollo Client", [
        r'"@apollo/client"\s*:\s*"([0-9][^"]{1,20})"',
        r'@apollo/client(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'ApolloClient\s*\(',
    ]),

    ("tRPC", [
        r'"@trpc/client"\s*:\s*"([0-9][^"]{1,20})"',
        r'@trpc/(?:client|react-query)(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # UTILITIES
    # ══════════════════════════════════════════════════════════════════════════

    ("jQuery", [
        r'jQuery\.fn\.jquery\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'\$\.fn\.jquery\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"jquery"\s*,\s*"([0-9][^"]{1,20})"',
        r'"jquery"\s*:\s*"([0-9][^"]{1,20})"',
        r'jquery(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'/jquery[.\-]([0-9][^/\s"\']{1,20})(?:\.min)?\.js',
    ]),

    ("Lodash", [
        r'_\.VERSION\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"lodash"\s*,\s*"([0-9][^"]{1,20})"',
        r'"lodash"\s*:\s*"([0-9][^"]{1,20})"',
        r'lodash(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Underscore.js", [
        r'/underscore[.\-]([0-9][^/\s"\']{1,20})(?:\.min)?\.js',
        r'"underscore"\s*:\s*"([0-9][^"]{1,20})"',
        r'underscore(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Moment.js", [
        r'moment\.version\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"moment"\s*,\s*"([0-9][^"]{1,20})"',
        r'"moment"\s*:\s*"([0-9][^"]{1,20})"',
        r'moment(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Day.js", [
        r'"dayjs"\s*,\s*"([0-9][^"]{1,20})"',
        r'"dayjs"\s*:\s*"([0-9][^"]{1,20})"',
        r'dayjs(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("date-fns", [
        r'"date-fns"\s*,\s*"([0-9][^"]{1,20})"',
        r'"date-fns"\s*:\s*"([0-9][^"]{1,20})"',
        r'date-fns(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Luxon", [
        r'"luxon"\s*:\s*"([0-9][^"]{1,20})"',
        r'luxon(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'DateTime\.now\s*\(',
    ]),

    ("UUID", [
        r'"uuid"\s*:\s*"([0-9][^"]{1,20})"',
        r'uuid(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("clsx / classnames", [
        r'"clsx"\s*:\s*"([0-9][^"]{1,20})"',
        r'"classnames"\s*:\s*"([0-9][^"]{1,20})"',
        r'clsx(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Immer", [
        r'"immer"\s*:\s*"([0-9][^"]{1,20})"',
        r'immer(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'produce\s*\(',
    ]),

    ("Ramda", [
        r'"ramda"\s*:\s*"([0-9][^"]{1,20})"',
        r'ramda(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # BUILD / TRANSPILE TOOLS
    # ══════════════════════════════════════════════════════════════════════════

    ("Webpack", [
        r'"webpack"\s*:\s*"([0-9][^"]{1,20})"',
        r'webpack(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'__webpack_require__|webpackJsonp|webpackChunk|webpackBootstrap',
    ]),

    ("Babel Runtime", [
        r'"@babel/runtime"\s*:\s*"([0-9][^"]{1,20})"',
        r'@babel/runtime(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'_interopRequireDefault|_classCallCheck',
    ]),

    ("TypeScript", [
        r'"typescript"\s*:\s*"([0-9][^"]{1,20})"',
        r'typescript(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("core-js", [
        r'"core-js"\s*:\s*"([0-9][^"]{1,20})"',
        r'core-js(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'core-js/modules/',
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # ANIMATION
    # ══════════════════════════════════════════════════════════════════════════

    ("GSAP", [
        r'gsap\.version\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"gsap"\s*,\s*"([0-9][^"]{1,20})"',
        r'"gsap"\s*:\s*"([0-9][^"]{1,20})"',
        r'gsap(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Framer Motion", [
        r'"framer-motion"\s*,\s*"([0-9][^"]{1,20})"',
        r'"framer-motion"\s*:\s*"([0-9][^"]{1,20})"',
        r'framer-motion(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'AnimatePresence|useAnimation\s*\(',
    ]),

    ("Anime.js", [
        r'"animejs"\s*:\s*"([0-9][^"]{1,20})"',
        r'animejs(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'anime\.version\s*=\s*["\']([0-9][^"\']{1,20})["\']',
    ]),

    ("Lottie", [
        r'"lottie-web"\s*:\s*"([0-9][^"]{1,20})"',
        r'lottie-web(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'lottie\.loadAnimation',
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # DATA VISUALIZATION
    # ══════════════════════════════════════════════════════════════════════════

    ("D3.js", [
        r'd3\.version\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"d3"\s*,\s*"([0-9][^"]{1,20})"',
        r'"d3"\s*:\s*"([0-9][^"]{1,20})"',
        r'd3(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Chart.js", [
        r'Chart\.version\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"chart\.js"\s*:\s*"([0-9][^"]{1,20})"',
        r'chart\.js(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Recharts", [
        r'"recharts"\s*,\s*"([0-9][^"]{1,20})"',
        r'"recharts"\s*:\s*"([0-9][^"]{1,20})"',
        r'recharts(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Highcharts", [
        r'Highcharts\.version\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"highcharts"\s*:\s*"([0-9][^"]{1,20})"',
        r'highcharts(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Apache ECharts", [
        r'"echarts"\s*:\s*"([0-9][^"]{1,20})"',
        r'echarts(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # FORMS & VALIDATION
    # ══════════════════════════════════════════════════════════════════════════

    ("React Hook Form", [
        r'"react-hook-form"\s*,\s*"([0-9][^"]{1,20})"',
        r'"react-hook-form"\s*:\s*"([0-9][^"]{1,20})"',
        r'react-hook-form(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'useForm\s*\(',
    ]),

    ("Formik", [
        r'"formik"\s*,\s*"([0-9][^"]{1,20})"',
        r'"formik"\s*:\s*"([0-9][^"]{1,20})"',
        r'formik(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Zod", [
        r'"zod"\s*,\s*"([0-9][^"]{1,20})"',
        r'"zod"\s*:\s*"([0-9][^"]{1,20})"',
        r'zod(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'z\.object\s*\(',
    ]),

    ("Yup", [
        r'"yup"\s*:\s*"([0-9][^"]{1,20})"',
        r'yup(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # INTERNATIONALIZATION
    # ══════════════════════════════════════════════════════════════════════════

    ("i18next", [
        r'"i18next"\s*,\s*"([0-9][^"]{1,20})"',
        r'"i18next"\s*:\s*"([0-9][^"]{1,20})"',
        r'i18next(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("react-i18next", [
        r'"react-i18next"\s*:\s*"([0-9][^"]{1,20})"',
        r'react-i18next(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'useTranslation\s*\(',
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # MONITORING / ANALYTICS
    # ══════════════════════════════════════════════════════════════════════════

    ("Sentry", [
        r'Sentry\.VERSION\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"@sentry/(?:browser|react|vue)"\s*:\s*"([0-9][^"]{1,20})"',
        r'@sentry/(?:browser|react)(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'Sentry\.init\s*\(',
    ]),

    ("Datadog RUM", [
        r'"@datadog/browser-rum"\s*:\s*"([0-9][^"]{1,20})"',
        r'@datadog/browser-rum(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'datadogRum\.init',
    ]),

    ("LogRocket", [
        r'"logrocket"\s*:\s*"([0-9][^"]{1,20})"',
        r'logrocket(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'LogRocket\.init',
    ]),

    ("Google Analytics", [
        r'ga\s*\(\s*["\']create["\']',
        r'gtag\s*\(',
        r'googletagmanager\.com/gtag',
    ]),

    ("Mixpanel", [
        r'"mixpanel-browser"\s*:\s*"([0-9][^"]{1,20})"',
        r'mixpanel-browser(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'mixpanel\.track\s*\(',
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # PAYMENTS
    # ══════════════════════════════════════════════════════════════════════════

    ("Stripe.js", [
        r'"@stripe/stripe-js"\s*:\s*"([0-9][^"]{1,20})"',
        r'@stripe/stripe-js(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'js\.stripe\.com/v([0-9]+)',
        r'Stripe\s*\(',
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # REAL-TIME
    # ══════════════════════════════════════════════════════════════════════════

    ("Socket.IO", [
        r'io\.version\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"socket\.io-client"\s*:\s*"([0-9][^"]{1,20})"',
        r'socket\.io(?:-client)?(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'io\.connect\s*\(',
    ]),

    ("Pusher", [
        r'"pusher-js"\s*:\s*"([0-9][^"]{1,20})"',
        r'pusher-js(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
        r'new\s+Pusher\s*\(',
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # 3D / CANVAS / WEBGL
    # ══════════════════════════════════════════════════════════════════════════

    ("Three.js", [
        r'THREE\.REVISION\s*=\s*["\']?([0-9][^"\';\s]{1,10})',
        r'"three"\s*,\s*"([0-9][^"]{1,20})"',
        r'"three"\s*:\s*"([0-9][^"]{1,20})"',
        r'three(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("React Three Fiber", [
        r'"@react-three/fiber"\s*:\s*"([0-9][^"]{1,20})"',
        r'@react-three/fiber(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("PixiJS", [
        r'PIXI\.VERSION\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"pixi\.js"\s*:\s*"([0-9][^"]{1,20})"',
        r'pixi\.js(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # MISC
    # ══════════════════════════════════════════════════════════════════════════

    ("PDF.js", [
        r'pdfjsLib\.version\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"pdfjs-dist"\s*:\s*"([0-9][^"]{1,20})"',
        r'pdfjs-dist(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Quill Editor", [
        r'Quill\.version\s*=\s*["\']([0-9][^"\']{1,20})["\']',
        r'"quill"\s*:\s*"([0-9][^"]{1,20})"',
        r'quill(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("TipTap", [
        r'"@tiptap/core"\s*:\s*"([0-9][^"]{1,20})"',
        r'@tiptap/core(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),

    ("Storybook", [
        r'"@storybook/react"\s*:\s*"([0-9][^"]{1,20})"',
        r'@storybook/(?:react|vue)(?:@|-)([0-9][^\s/"\',)\]]{1,20})',
    ]),
]


# ─────────────────────────────────────────────────────────────────────────────
CATEGORIES = {
    "Framework":        ["React", "Vue.js", "Angular", "AngularJS", "Svelte",
                         "Solid.js", "Preact", "Ember.js", "Backbone.js"],
    "Meta-Framework":   ["Next.js", "Nuxt.js", "Gatsby", "Remix", "Astro"],
    "UI Library":       ["Bootstrap", "Tailwind CSS", "Material UI (MUI)", "Ant Design",
                         "Chakra UI", "Vuetify", "shadcn/ui", "Radix UI",
                         "Headless UI", "PrimeReact", "Mantine"],
    "State Management": ["Redux", "Redux Toolkit", "React-Redux", "MobX",
                         "Zustand", "Recoil", "Jotai", "XState"],
    "Routing":          ["React Router", "Vue Router", "TanStack Router"],
    "Data Fetching":    ["Axios", "TanStack Query", "SWR", "GraphQL",
                         "Apollo Client", "tRPC"],
    "Utility":          ["jQuery", "Lodash", "Underscore.js", "Moment.js",
                         "Day.js", "date-fns", "Luxon", "UUID",
                         "clsx / classnames", "Immer", "Ramda"],
    "Build Tool":       ["Webpack", "Babel Runtime", "TypeScript", "core-js"],
    "Animation":        ["GSAP", "Framer Motion", "Anime.js", "Lottie"],
    "Data Viz":         ["D3.js", "Chart.js", "Recharts", "Highcharts",
                         "Apache ECharts"],
    "Forms":            ["React Hook Form", "Formik", "Zod", "Yup"],
    "i18n":             ["i18next", "react-i18next"],
    "Monitoring":       ["Sentry", "Datadog RUM", "LogRocket",
                         "Google Analytics", "Mixpanel"],
    "Payments":         ["Stripe.js"],
    "Real-time":        ["Socket.IO", "Pusher"],
    "3D / Canvas":      ["Three.js", "React Three Fiber", "PixiJS"],
    "Editor":           ["Quill Editor", "TipTap"],
    "Other":            ["PDF.js", "Storybook"],
}


def get_category(lib_name: str) -> str:
    for cat, libs in CATEGORIES.items():
        if lib_name in libs:
            return cat
    return "Other"


# ─────────────────────────────────────────────────────────────────────────────

def fetch_bundle(url: str) -> str | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.HTTPError as e:
        console.print(f"[red]HTTP {e.response.status_code}: {e}[/red]")
    except requests.exceptions.ConnectionError as e:
        console.print(f"[red]Connection error: {e}[/red]")
    except requests.exceptions.Timeout:
        console.print("[red]Request timed out (30 s).[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
    return None


def is_webpack_bundle(content: str) -> bool:
    markers = [
        "__webpack_require__", "webpackJsonp", "webpackChunk",
        "webpack/runtime", "webpackBootstrap", "webpack_exports",
    ]
    return any(m in content for m in markers)


def detect_libraries(content: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for lib_name, patterns in LIBRARY_PATTERNS:
        for pattern in patterns:
            try:
                m = re.search(pattern, content, re.IGNORECASE)
            except re.error:
                continue
            if m:
                if m.lastindex and m.lastindex >= 1:
                    raw = m.group(1)
                    version = re.sub(r'[^0-9a-zA-Z.\-+~^*]', '', raw)
                    version = version[:25] if version else "detected"
                else:
                    version = "detected (version unknown)"
                found[lib_name] = version
                break
    return found


def bundle_stats(content: str) -> dict:
    return {
        "size_kb":      round(len(content.encode("utf-8")) / 1024, 1),
        "lines":        content.count("\n") + 1,
        "is_minified":  content.count("\n") < 20,
        "module_count": len(re.findall(r'__webpack_require__\s*\(', content)),
    }


# ─────────────────────────────────────────────────────────────────────────────

def scan(url: str) -> None:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    console.print()
    console.print(Panel.fit(
        "[bold cyan]⚡ Webpack .js Bundle Scanner[/bold cyan]\n"
        f"[dim]{url}[/dim]",
        border_style="cyan",
        padding=(0, 2),
    ))

    # Fetch
    console.print("\n[bold]Fetching bundle …[/bold]")
    content = fetch_bundle(url)
    if content is None:
        console.print("[red]❌  Could not fetch the bundle. Aborting.[/red]")
        sys.exit(1)

    # Sanity check — make sure it's JS, not an HTML error page
    if content.lstrip().startswith("<!"):
        console.print("[red]❌  The URL returned HTML, not a JavaScript file. "
                      "Check the URL is correct.[/red]")
        sys.exit(1)

    stats  = bundle_stats(content)
    is_wp  = is_webpack_bundle(content)

    console.print(
        f"  Size     : [cyan]{stats['size_kb']:,} KB[/cyan]\n"
        f"  Lines    : [cyan]{stats['lines']:,}[/cyan]\n"
        f"  Minified : {'[yellow]yes[/yellow]' if stats['is_minified'] else '[green]no[/green]'}\n"
        f"  Webpack modules referenced: [cyan]{stats['module_count']:,}[/cyan]\n"
        f"  Webpack bundle: {'[bold green]✓ confirmed[/bold green]' if is_wp else '[yellow]⚠ not confirmed (may still contain libraries)[/yellow]'}"
    )

    # Detect
    console.print("\n[bold]Scanning for libraries …[/bold]")
    found = detect_libraries(content)

    # Output
    console.print()
    if not found:
        console.print(Panel.fit(
            "[yellow]No known libraries detected.[/yellow]\n"
            "[dim]The bundle may be heavily obfuscated, tree-shaken beyond recognition,\n"
            "or use libraries not yet in the fingerprint database.[/dim]",
            border_style="yellow",
        ))
        return

    console.print(Panel.fit(
        f"[bold green]✅  {len(found)} librar{'y' if len(found)==1 else 'ies'} detected[/bold green]",
        border_style="green",
        padding=(0, 2),
    ))

    # Group by category
    grouped: dict[str, list[tuple[str, str]]] = {}
    for lib, ver in sorted(found.items()):
        cat = get_category(lib)
        grouped.setdefault(cat, []).append((lib, ver))

    table = Table(
        title="📦  Detected Libraries & Versions",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
        border_style="bright_black",
        expand=False,
    )
    table.add_column("Category",  style="bold cyan",    min_width=16, no_wrap=True)
    table.add_column("Library",   style="bold white",   min_width=24)
    table.add_column("Version",   style="bright_green", min_width=14)

    first = True
    for cat in list(CATEGORIES.keys()) + ["Other"]:
        if cat not in grouped:
            continue
        if not first:
            table.add_row("", "", "")
        first = False
        for i, (lib, ver) in enumerate(grouped[cat]):
            table.add_row(cat if i == 0 else "", lib, ver)

    console.print(table)
    console.print()


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        console.print("[bold]Usage:[/bold]  python webpack_scanner.py <bundle_url>\n")
        console.print("[dim]Examples:[/dim]")
        console.print("  python webpack_scanner.py https://example.com/static/js/main.abc123.js")
        console.print("  python webpack_scanner.py https://example.com/assets/vendor.js\n")
        sys.exit(0)

    scan(sys.argv[1])