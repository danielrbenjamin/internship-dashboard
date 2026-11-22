import {useEffect, useId, useState, type KeyboardEvent} from "react";
import {ChevronDown} from "lucide-react";

type Option = {value: string; label: string; keywords?: string};

export function SearchableSelect({label, value, options, onChange}: {
  label: string; value: string; options: Option[]; onChange: (value: string) => void;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const selected = options.find(option => option.value === value);
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const matches = options.filter(option => words.every(word =>
    (option.label + " " + (option.keywords ?? "")).toLowerCase().includes(word)));
  const visible = matches.slice(0, 50);
  const highlighted = open && visible[active] ? id + "-" + active : undefined;

  useEffect(() => {
    if (highlighted) document.getElementById(highlighted)?.scrollIntoView({block: "nearest"});
  }, [highlighted]);

  function choose(option: Option) {
    onChange(option.value);
    setOpen(false);
    setQuery("");
  }

  function keys(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape" && open) {
      event.stopPropagation();
      setOpen(false);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        setQuery("");
        setActive(0);
      } else {
        const delta = event.key === "ArrowDown" ? 1 : -1;
        setActive(Math.max(0, Math.min(visible.length - 1, active + delta)));
      }
    } else if (event.key === "Enter" && open) {
      event.preventDefault();
      if (visible[active]) choose(visible[active]);
    }
  }

  return <div className="searchable-select">
    <label htmlFor={id}>{label}</label>
    <div className="select-control">
      <input id={id} role="combobox" aria-autocomplete="list" aria-expanded={open} aria-controls={id + "-options"}
        aria-activedescendant={highlighted} autoComplete="off"
        value={open ? query : selected?.label ?? ""}
        placeholder={open ? "Search " + label.toLowerCase() : options[0]?.label}
        onClick={() => {if (!open) {setQuery(""); setActive(0); setOpen(true);}}}
        onChange={event => {setQuery(event.target.value); setActive(0); setOpen(true);}}
        onFocus={() => {setQuery(""); setActive(0); setOpen(true);}}
        onBlur={() => setOpen(false)} onKeyDown={keys} />
      <ChevronDown size={15} aria-hidden="true" />
    </div>
    <div className="select-popup" hidden={!open}>
      <ul id={id + "-options"} role="listbox" aria-label={label}>
        {visible.map((option, index) => <li id={id + "-" + index} key={option.value} role="option"
          aria-selected={option.value === value} data-active={index === active}
          onPointerMove={() => setActive(index)} onMouseDown={event => event.preventDefault()}
          onClick={() => choose(option)}>{option.label}</li>)}
      </ul>
      {!visible.length && <p role="status">No matches</p>}
      {matches.length > visible.length && <p role="status">Type to narrow {matches.length.toLocaleString()} options</p>}
    </div>
  </div>;
}
