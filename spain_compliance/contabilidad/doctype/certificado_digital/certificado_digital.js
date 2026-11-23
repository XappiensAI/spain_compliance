// Copyright (c) 2026, Xappiens and contributors
// License: MIT

const SC_ESTADO_COLOR = {
	Vigente: "green",
	"Próximo a caducar": "orange",
	Caducado: "red",
};

frappe.ui.form.on("Certificado Digital", {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.estado) {
			frm.page.set_indicator(__(frm.doc.estado), SC_ESTADO_COLOR[frm.doc.estado] || "gray");
		}
		if (!frm.is_new() && frm.doc.valido_hasta) {
			const dias = frappe.datetime.get_day_diff(frm.doc.valido_hasta, frappe.datetime.get_today());
			const color = SC_ESTADO_COLOR[frm.doc.estado] || "blue";
			const texto =
				dias < 0
					? __("Caducó hace {0} días.", [-dias])
					: __("Caduca en {0} días ({1}).", [dias, frappe.datetime.str_to_user(frm.doc.valido_hasta)]);
			frm.dashboard.set_headline_alert(texto, color);
		}
	},
});
