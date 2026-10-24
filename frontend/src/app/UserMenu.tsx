import {
  Button,
  Menu,
  MenuDivider,
  MenuGroup,
  MenuGroupHeader,
  MenuItem,
  MenuItemRadio,
  MenuList,
  MenuPopover,
  MenuTrigger,
} from "@fluentui/react-components";
import type { ReactElement } from "react";
import { signOut, useRoles } from "../auth";
import {
  THEME_NAMES,
  THEME_PACKS,
  isThemeName,
  isThemePackId,
  useThemeStore,
  type ThemeName,
} from "../design-system";
import { SandboxToggle } from "../features/sandbox/SandboxToggle";
import { useDomainData } from "./domain";

const MODE_LABELS: Readonly<Record<ThemeName, string>> = {
  light: "Light",
  dark: "Dark",
  "high-contrast": "High contrast",
};

/**
 * Shows the display role(s), the theme mode and pack pickers and the sandbox switch, and offers
 * sign out (which also clears the remembered domain). Theme and sandbox choices are UI
 * preferences only; they never change what the API allows.
 */
export function UserMenu(): ReactElement {
  const { label } = useRoles();
  const data = useDomainData();
  const themeName = useThemeStore((s) => s.themeName);
  const packId = useThemeStore((s) => s.packId);
  const setTheme = useThemeStore((s) => s.setTheme);
  const setPack = useThemeStore((s) => s.setPack);
  return (
    <>
      <SandboxToggle />
      <Menu
        checkedValues={{ mode: [themeName], pack: [packId] }}
        onCheckedValueChange={(_event, { name, checkedItems }) => {
          const value = checkedItems[0];
          if (name === "mode" && isThemeName(value)) setTheme(value);
          if (name === "pack" && isThemePackId(value)) setPack(value);
        }}
      >
        <MenuTrigger disableButtonEnhancement>
          <Button appearance="subtle">{`Account: ${label}`}</Button>
        </MenuTrigger>
        <MenuPopover>
          <MenuList>
            <MenuGroup>
              <MenuGroupHeader>Theme mode</MenuGroupHeader>
              {THEME_NAMES.map((name) => (
                <MenuItemRadio key={name} name="mode" value={name}>
                  {MODE_LABELS[name]}
                </MenuItemRadio>
              ))}
            </MenuGroup>
            <MenuDivider />
            <MenuGroup>
              <MenuGroupHeader>Theme pack</MenuGroupHeader>
              {Object.values(THEME_PACKS).map((pack) => (
                <MenuItemRadio key={pack.id} name="pack" value={pack.id}>
                  {pack.displayName}
                </MenuItemRadio>
              ))}
            </MenuGroup>
            <MenuDivider />
            <MenuItem
              onClick={() => {
                data?.forget();
                void signOut();
              }}
            >
              Sign out
            </MenuItem>
          </MenuList>
        </MenuPopover>
      </Menu>
    </>
  );
}
