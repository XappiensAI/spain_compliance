// Copyright (c) 2026, Xappiens and contributors
// License: MIT

frappe.listview_settings["Certificado Digital"] = {
	add_fields: ["estado", "valido_hasta"],
	get_indicator(doc) {
		const color = { Vigente: "green", "Próximo a caducar": "orange", Caducado: "red" }[doc.estado];
		return [__(doc.estado), color || "gray", "estado,=," + doc.estado];
	},
};
