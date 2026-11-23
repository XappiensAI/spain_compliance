// Copyright (c) 2026, Xappiens and contributors
// License: MIT

frappe.ui.form.on("SII Registro", {
	refresh(frm) {
		if (frm.is_new() || !frappe.user.has_role(["Accounts Manager", "System Manager"])) return;
		const llamar = (method, args, msg) =>
			frappe.call({ method, args, freeze: true, freeze_message: msg }).then(() => frm.reload_doc());
		frm.add_custom_button(__("Enviar"), () =>
			llamar("spain_compliance.api.sii.enviar", { registros: [frm.doc.name] }, __("Enviando a la AEAT…")),
		);
		frm.add_custom_button(__("Consultar en la AEAT"), () =>
			llamar("spain_compliance.api.sii.consultar", { registros: [frm.doc.name] }, __("Consultando…")),
		);
	},
});
