CREATE TEMP TABLE demo_files(folder_path text, name text);
INSERT INTO demo_files VALUES ('Turbines/Product_Descriptions and spare parts','README_Download_References.md'),('Turbines/Drawings','README_Download_References.md'),('Turbines/Manuals','README_Download_References.md'),('Turbines/Inspection or Incident','README_Download_References.md'),('Turbines/SOPs','README_Download_References.md'),('Turbines/Sensors','README_Download_References.md'),('Turbines','README_Download_References_Supplement.md'),('Turbines/Work_Orders','generate_work_orders.py'),('Turbines/Maintenance','Steam_Turbine_Installation_Procedure.html.redirect'),('Turbines/Inspection or Incident','NDT_Report_Turbine_Bearings.html.redirect'),('Turbines/SOPs','Turbine_StartUp_Procedure_16MW.html.redirect'),('Turbines/Asset_Register','Turbine_Asset_Register_200.xlsx'),('Turbines/SOPs','Checklist_Turbine_Prestartup.html.redirect'),('Turbines/Inspection or Incident','ITP_Gas_Turbine_Inspection_Test_Plan.html.redirect'),('Turbines/SOPs','SOP_Turbine_Checklist_Jindal.html.redirect');
SELECT d.id
FROM documents d
JOIN document_catalog c ON c.id=d.catalog_id
JOIN demo_files f ON f.name=c.name AND f.folder_path=c.folder_path
WHERE COALESCE(c.metadata->>'asset_domain','')='Turbines'
  AND d.status <> 'chunked'
ORDER BY d.id
LIMIT 15;