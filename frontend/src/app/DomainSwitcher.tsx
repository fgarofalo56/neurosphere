import { Dropdown, Label, Option, makeStyles, tokens } from "@fluentui/react-components";
import { useId, type ReactElement } from "react";
import {
  NO_DOMAINS_MESSAGE,
  domainLabel,
  useDomainData,
  useSelectedDomain,
  type DomainEntry,
} from "./domain";

const useStyles = makeStyles({
  message: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase300 },
  row: { display: "flex", alignItems: "center", columnGap: tokens.spacingHorizontalS },
  dropdown: { minWidth: "260px" },
});

function labelFor(domains: readonly DomainEntry[], domainId: string): string {
  const match = domains.find((d) => d.domain_id === domainId);
  return match === undefined ? domainId : domainLabel(match);
}

/**
 * Header control listing the caller's readable domains. Choosing one writes `?domain_id=` on the
 * current page (and the nav links follow). Renders nothing when no domain provider is mounted.
 */
export function DomainSwitcher(): ReactElement | null {
  const styles = useStyles();
  const data = useDomainData();
  const controlId = useId();
  const { domainId, domains, setDomain } = useSelectedDomain();

  if (data === null) return null;
  // 403 and a 200 with no items both mean "nothing assigned"; no domain is invented.
  if (data.status === "forbidden" || (data.status === "ready" && domains.length === 0)) {
    return (
      <span role="status" className={styles.message}>
        {NO_DOMAINS_MESSAGE}
      </span>
    );
  }
  if (data.status === "error") {
    return (
      <span role="status" className={styles.message}>
        Domains could not be loaded
      </span>
    );
  }
  const loading = data.status === "loading";
  const inList = domains.some((d) => d.domain_id === domainId);

  return (
    <div className={styles.row}>
      <Label htmlFor={controlId}>Domain</Label>
      <Dropdown
        id={controlId}
        className={styles.dropdown}
        disabled={loading}
        placeholder={loading ? "Loading domains..." : "Select a domain"}
        value={domainId === "" ? "" : labelFor(domains, domainId)}
        selectedOptions={inList ? [domainId] : []}
        onOptionSelect={(_event, option) => {
          if (option.optionValue !== undefined) setDomain(option.optionValue);
        }}
      >
        {domains.map((d) => (
          <Option key={d.domain_id} value={d.domain_id} text={domainLabel(d)}>
            {domainLabel(d)}
          </Option>
        ))}
      </Dropdown>
    </div>
  );
}
