(() => {
  const toggle = document.querySelector(".nav-toggle");
  const navigation = document.querySelector(".site-nav");

  function setNavigation(open) {
    if (!toggle || !navigation) return;
    navigation.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", String(open));
    const label = toggle.querySelector(".sr-only");
    if (label) label.textContent = open ? "Close navigation" : "Open navigation";
  }

  toggle?.addEventListener("click", () => {
    setNavigation(toggle.getAttribute("aria-expanded") !== "true");
  });

  navigation?.addEventListener("click", (event) => {
    if (event.target.closest("a")) setNavigation(false);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setNavigation(false);
  });

  const year = String(new Date().getFullYear());
  document.querySelectorAll("[data-current-year]").forEach((element) => {
    element.textContent = year;
  });
})();
