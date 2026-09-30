// Soundings: Swagger UI bootstrap. Kept in a file (not inline) so the page works
// under our Content-Security-Policy (script-src 'self').
window.addEventListener("DOMContentLoaded", function () {
  var root = document.getElementById("swagger-ui");
  window.ui = SwaggerUIBundle({
    url: root.getAttribute("data-openapi-url"),
    dom_id: "#swagger-ui",
    deepLinking: true,
    layout: "BaseLayout",
    presets: [SwaggerUIBundle.presets.apis],
    // Never call validator.swagger.io: everything must work air-gapped.
    validatorUrl: null,
    showExtensions: true,
    persistAuthorization: false,
  });
});
