# polysignal-lab - Project Index

## 📖 Project Overview

Auto-generated project index maintained by the Fractal Multi-level Index System.

## 📁 Directory Structure

```
├── frontend/ (3 files)
  ├── src/ (4 files)
      ├── custom/ (10 files)
    ├── components/ (11 files)
      ├── layout/ (8 files)
        ├── data/ (2 files)
      ├── ui/ (22 files)
    ├── config/ (1 files)
    ├── context/ (6 files)
      ├── errors/ (5 files)
      ├── leaderboard/ (2 files)
      ├── overview/ (2 files)
      ├── reporting/ (2 files)
      ├── signals/ (2 files)
      ├── strategy-status/ (2 files)
      ├── system-health/ (2 files)
    ├── hooks/ (3 files)
    ├── lib/ (6 files)
      ├── api/ (4 files)
    ├── routes/ (1 files)
      ├── (errors)/ (5 files)
      ├── _authenticated/ (7 files)
        ├── errors/ (1 files)
    ├── test-utils/ (4 files)
├── scripts/ (6 files)
  ├── archive/ (2 files)
  ├── polysignal_lab/ (4 files)
    ├── alpha/ (16 files)
    ├── app/ (15 files)
      ├── services/ (10 files)
    ├── dashboard/ (3 files)
    ├── data/ (13 files)
    ├── domain/ (15 files)
    ├── nautilus_bridge/ (5 files)
      ├── strategies/ (1 files)
    ├── nautilus_runtime/ (29 files)
      ├── strategies/ (3 files)
      ├── strategy/ (3 files)
    ├── observability/ (6 files)
    ├── reporting/ (6 files)
    ├── publish/ (4 files)
    ├── signal_layer/ (7 files)
    ├── storage/ (5 files)
    ├── strategies/ (20 files)
├── tests/ (107 files)
  ├── fixtures/ (1 files)
```

## 🔗 Dependency Graph

```mermaid
graph TD
  vite_config[vite.config]
  knip_config[knip.config]
  vite_env_d[vite-env.d]
  tanstack_table_d[tanstack-table.d]
  routeTree_gen[routeTree.gen]
  setup[setup]
  fixtures[fixtures]
  cookies[cookies]
  utils[utils]
  utils_test[utils.test]
  handle_server_error[handle-server-error]
  handle_server_error_test[handle-server-error.test]
  cookies_test[cookies.test]
  use_table_url_state[use-table-url-state]
  use_table_url_state_test[use-table-url-state.test]
  fonts[fonts]
  types[types]
  hooks[hooks]
  client[client]
  client_test[client.test]
  sidebar_data[sidebar-data]
  sidebar_data_test[sidebar-data.test]
  main[main]
  render_with_query_client[render-with-query-client]
  __root[__root]
  use_mobile[use-mobile]
  theme_provider[theme-provider]
  search_provider[search-provider]
  search_provider_test[search-provider.test]
  layout_provider[layout-provider]
  font_provider[font-provider]
  direction_provider[direction-provider]
  theme_switch[theme-switch]
  skip_to_main[skip-to-main]
  search[search]
  password_input[password-input]
  password_input_test[password-input.test]
  navigation_progress[navigation-progress]
  confirm_dialog[confirm-dialog]
  confirm_dialog_test[confirm-dialog.test]
  config_drawer[config-drawer]
  config_drawer_test[config-drawer.test]
  command_menu[command-menu]
  system_health[system-health]
  strategy_status[strategy-status]
  signals[signals]
  route[route]
  reporting[reporting]
  vite_config --> path_from__path_
  vite_config --> __defineConfig___from__vite_
  vite_config --> plugin_react_
  knip_config --> type___KnipConfig___from__knip_
  knip_config --> knip
  tanstack_table_d --> react_table_
  routeTree_gen --> __root_
  routeTree_gen --> route_
  routeTree_gen --> index_
  setup --> vitest_
  setup --> react_
  setup --> __afterEach__vi___from__vitest_
  fixtures --> type__
  fixtures --> types
  cookies --> cookies_
  utils --> __type_ClassValue__clsx___from__clsx_
  utils --> __twMerge___from__tailwind_merge_
  utils --> clsx
  utils_test --> __describe__expect__it___from__vitest_
  utils_test --> utils_
  utils_test --> vitest
  handle_server_error --> __AxiosError___from__axios_
  handle_server_error --> __toast___from__sonner_
  handle_server_error --> axios
  handle_server_error_test --> __AxiosError___from__axios_
  handle_server_error_test --> __beforeEach__describe__expect__it__vi___from__vitest_
  handle_server_error_test --> handle_server_error_
  cookies_test --> cookies_
  cookies_test --> __beforeEach__describe__expect__it___from__vitest_
  use_table_url_state --> __useMemo__useState___from__react_
  use_table_url_state --> type__
  use_table_url_state --> react
  use_table_url_state_test --> __type_Mock__describe__expect__it__vi___from__vitest_
  use_table_url_state_test --> react_
  use_table_url_state_test --> use_table_url_state_
  hooks --> react_query_
  hooks --> client_
  hooks --> react_query
  client --> type__
  client --> types
  client_test --> __afterEach__describe__expect__it__vi___from__vitest_
  client_test --> client_
  client_test --> vitest
  types --> react_router_
  types --> react_router
  sidebar_data --> _
  sidebar_data --> types_
  sidebar_data --> types
  sidebar_data_test --> __describe__expect__it___from__vitest_
  sidebar_data_test --> sidebar_data_
  sidebar_data_test --> vitest
  main --> __StrictMode___from__react_
  main --> client_
  main --> __AxiosError___from__axios_
  render_with_query_client --> type___ReactElement___from__react_
  render_with_query_client --> react_query_
  render_with_query_client --> react_
  __root --> react_query_
  __root --> react_router_
  __root --> react_query_devtools_
  use_mobile --> __as_React_from__react_
  use_mobile --> react
  theme_provider --> __createContext__useContext__useEffect__useState__useMemo___from__react_
  theme_provider --> cookies_
  theme_provider --> react
  search_provider --> __createContext__useContext__useEffect__useState___from__react_
  search_provider --> command_menu_
  search_provider --> react
  search_provider_test --> __beforeEach__describe__expect__it__vi___from__vitest_
  search_provider_test --> react_
  search_provider_test --> user_event_
  layout_provider --> __createContext__useContext__useState___from__react_
  layout_provider --> cookies_
  layout_provider --> react
  font_provider --> __createContext__useEffect__useState___from__react_
  font_provider --> fonts_
  font_provider --> cookies_
  direction_provider --> __createContext__useContext__useEffect__useState___from__react_
  direction_provider --> react_direction_
  direction_provider --> cookies_
  theme_switch --> __useEffect___from__react_
  theme_switch --> __Check__Moon__Sun___from__lucide_react_
  theme_switch --> utils_
  search --> __SearchIcon___from__lucide_react_
  search --> utils_
  search --> search_provider_
  password_input --> __as_React_from__react_
  password_input --> __Eye__EyeOff___from__lucide_react_
  password_input --> utils_
  password_input_test --> __describe__expect__it___from__vitest_
  password_input_test --> react_
  password_input_test --> user_event_
  navigation_progress --> __useEffect__useRef___from__react_
  navigation_progress --> react_router_
  navigation_progress --> LoadingBar____type_LoadingBarRef___from__react_top_loading_bar_
  confirm_dialog --> utils_
  confirm_dialog --> _
  confirm_dialog --> button_
  confirm_dialog_test --> type___SubmitEvent___from__react_
  confirm_dialog_test --> __describe__expect__it__vi___from__vitest_
  confirm_dialog_test --> react_
  config_drawer --> __type_SVGProps___from__react_
  config_drawer --> react_radio_group_
  config_drawer --> __CircleCheck__RotateCcw__Settings___from__lucide_react_
  config_drawer_test --> cookies_
  config_drawer_test --> __beforeEach__describe__expect__it__vi___from__vitest_
  config_drawer_test --> react_
  command_menu --> React_from__react_
  command_menu --> react_router_
  command_menu --> __ArrowRight__ChevronRight__Laptop__Moon__Sun___from__lucide_react_
  system_health --> react_router_
  system_health --> system_health_
  system_health --> react_router
  strategy_status --> react_router_
  strategy_status --> strategy_status_
  strategy_status --> react_router
  signals --> react_router_
  signals --> signals_
  signals --> react_router
  route --> react_router_
  route --> authenticated_layout_
  route --> react_router
  reporting --> react_router_
  reporting --> reporting_
  reporting --> react_router
```

## 📊 Statistics

- Total folders: 46
- Total files: 388

---

🔄 **Self-reference**: When project structure changes, update this index

🎼 Generated by [Project Multilevel Index](https://github.com/Claudate/project-multilevel-index)
