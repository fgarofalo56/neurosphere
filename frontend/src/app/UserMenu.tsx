import {
  Button,
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
} from "@fluentui/react-components";
import type { ReactElement } from "react";
import { signOut, useRoles } from "../auth";
import { useDomainData } from "./domain";

/** Shows the display role(s) and offers sign out, which also clears the remembered domain. */
export function UserMenu(): ReactElement {
  const { label } = useRoles();
  const data = useDomainData();
  return (
    <Menu>
      <MenuTrigger disableButtonEnhancement>
        <Button appearance="subtle">{`Account: ${label}`}</Button>
      </MenuTrigger>
      <MenuPopover>
        <MenuList>
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
  );
}
