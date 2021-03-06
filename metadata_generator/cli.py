#!/usr/bin/env python3
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
import glob
import os
import json
from datetime import datetime
import click
from lxml import etree
from jinja2 import Environment, PackageLoader, select_autoescape, FileSystemLoader
import pkg_resources

SERVICE_TEMPLATES = {
    "inspire":"iso19119_nl_profile_2.0_template_inspire_harmonized.xml",
    "noninspire":"iso19119_nl_profile_2.0_regular.xml",
}
CODELIST_JSON_FILE = "data/json/codelists.json"

SERVICE_TYPES = ['CSW', 'WMS', 'WMTS', 'WFS', 'WCS', 'SOS', 'ATOM', 'TMS']
SERVICE_TYPES_CLI = ['CSW', 'WMS', 'WMTS', 'WFS', 'WCS', 'SOS', 'ATOM', 'TMS', 'IN_JSON']
NGR_HOST_TYPES = ['PROD', 'TEST']

def clean_service_cap_url(url, service_type):
    if service_type == "ATOM":
        return url
    url_parts = list(urlparse(url))
    query = {'request':'GetCapabilities','service':service_type.upper()}
    url_parts[4] = urlencode(query)
    return urlunparse(url_parts)

def get_inspire_theme_label(data_json):
    inspire_mode = data_json["inspire"]
    if inspire_mode:
        json_path = pkg_resources.resource_filename(__name__, CODELIST_JSON_FILE)
        with open(json_path, 'r') as json_file:
            codelists_json = json.loads(json_file.read())
            inspire_themes_codelist = codelists_json['inspire_themes']
            inspire_theme_uri = data_json['inspire_theme_uri']
            if inspire_theme_uri not in inspire_themes_codelist:
                raise Exception(f"inspire theme uri {inspire_theme_uri} unknown. See https://www.eionet.europa.eu/gemet/nl/inspire-themes/ for supported values.")
            return inspire_themes_codelist[inspire_theme_uri]
    return ""

def get_inspire_fields_by_ogc_service_type(ogc_service_type):
    # "inspire_service_type": "view",
    json_path = pkg_resources.resource_filename(__name__, CODELIST_JSON_FILE)
    with open(json_path, 'r') as json_file:
        codelists_json = json.loads(json_file.read())
        inspire_servicetypes_codelist = codelists_json["codelist_inspire_service_types"]
        for item in inspire_servicetypes_codelist:
            if ogc_service_type in item["ogc_service_types"]:
                return item

def get_service_protocol_values(service_type):
    # "service_protocol_name": "OGC:WMS",
    # "service_protocol_url": "http://www.opengeospatial.org/standards/wms"
    json_path = pkg_resources.resource_filename(__name__, CODELIST_JSON_FILE)
    with open(json_path, 'r') as json_file:
        codelists_json = json.loads(json_file.read())
        inspire_servicetypes_codelist = codelists_json["codelist_protocol"]
        return inspire_servicetypes_codelist[service_type]

def get_spatial_dataservice_categories():
    json_path = pkg_resources.resource_filename(__name__, CODELIST_JSON_FILE)
    with open(json_path, 'r') as json_file:
        codelists_json = json.loads(json_file.read())
        inspire_servicetypes_codelist = codelists_json["codelist_protocol"]
        categories = [inspire_servicetypes_codelist[key]["spatial_dataservice_category"] for key in inspire_servicetypes_codelist.keys() if "spatial_dataservice_category" in inspire_servicetypes_codelist[key]]
        return categories

def get_service_template(data_json):
    inspire = data_json["inspire"]
    if inspire:
        result = SERVICE_TEMPLATES["inspire"]
    else:
        result = SERVICE_TEMPLATES["noninspire"]
    return result

def get_service_url(data_json, service_type):
    # for now do not generate urls dynamically but use fallback 
    # based on key service_capabilities_url_<service_type>
    service_type_string = service_type.lower().replace(" ", "_")
    key = f"service_capabilities_url_{service_type_string}"
    if not key in data_json:
        raise Exception(f"key {key} missing in values-json input")
    url = data_json[key]
    url = clean_service_cap_url(url, service_type)
    return url

def add_dynamic_fields(data_json, ogc_service_type):
    md_date_stamp = datetime.today().strftime('%Y-%m-%d')
    title = data_json["service_title"]
    if not title.lower().endswith(ogc_service_type.lower()):
        data_json["service_title"] = f"{title} {ogc_service_type}"
    data_json["md_date_stamp"] = md_date_stamp

    if not "service_revision_date" in data_json or not data_json["service_revision_date"]:
        data_json["service_revision_date"] = md_date_stamp
    data_json["service_type"] = ogc_service_type
    protocol_fields = get_service_protocol_values(ogc_service_type)
    data_json.update(protocol_fields)
    service_capabilities_url = get_service_url(data_json, ogc_service_type)
    data_json["service_capabilities_url"] = service_capabilities_url
    # remove keywords that are equal to spatial_dataservice_category_label (
    # these kw are already taken care of by get_inspire_fields_by_ogc_service_type
    categories = get_spatial_dataservice_categories()
    kw_to_delete = [kw for kw in data_json["keywords"] if kw in categories]
    for kw in kw_to_delete:
        data_json["keywords"].remove(kw)
    # enfore lowercase keywords
    data_json["keywords"] = [kw.lower() for kw in data_json["keywords"]]
    # some inspire related fields are also mandatory in the "vanilla" NL profiel
    inspire_fields = get_inspire_fields_by_ogc_service_type(ogc_service_type)
    data_json.update(inspire_fields)
    inspire_theme_label = get_inspire_theme_label(data_json)
    if inspire_theme_label:
        data_json["inspire_theme_label"] = inspire_theme_label
    return data_json

def render_template(template_path, data_json):
    env = Environment( loader=PackageLoader('metadata_generator', 'data/templates'),
        autoescape=select_autoescape(['xml']))
    template = env.get_template(template_path)
    result = template.render(data_json)
    return result

def get_md_identifier(json_path):
    with open(json_path, 'r') as json_file:
        config_json = json.loads(json_file.read())
        return config_json["md_identifier"]

def get_ogc_service_type(json_path):
    with open(json_path, 'r') as json_file:
        config_json = json.loads(json_file.read())
        return config_json["ogc_service_type"]

def generate_service_metadata(json_path, service_type, ngr_host):
    with open(json_path, 'r') as json_file:
        config_json = json.loads(json_file.read())
        if ngr_host == "PROD":
            config_json["ngr_host"] = "https://nationaalgeoregister.nl"
        if ngr_host == "TEST":
            config_json["ngr_host"] = "https://ngr.acceptatie.nationaalgeoregister.nl"
        service_template = get_service_template(config_json)
        config_json = add_dynamic_fields(config_json, service_type)
        md_record = render_template(service_template, config_json)
        parser = etree.XMLParser(remove_comments=True, remove_blank_text=True)
        tree = etree.fromstring(md_record.encode('utf-8'), parser=parser)
        return etree.tostring(tree, pretty_print=True).decode('utf-8')

def validate_xml_form(xml_string):
    result = ""
    try:
        parser = etree.XMLParser()
        etree.fromstring(xml_string.encode('utf-8'), parser=parser)
    except IOError:
        result = "Invalid File"
    # check for XML syntax errors
    except etree.XMLSyntaxError as err:
        result = "XML Syntax Error: {0}".format(err.msg)
    return result

def validate_service_metadata(xml_string):
    result = validate_xml_form(xml_string)
    if result:
        return result
    schema_path = pkg_resources.resource_filename(__name__, "data/schema/schemas.opengis.net/csw/2.0.2/profiles/apiso/1.0.0/apiso.xsd")
    with open(schema_path, 'rb') as xml_schema_file:
        schema_doc = etree.XML(xml_schema_file.read(), base_url=schema_path)
        schema = etree.XMLSchema(schema_doc)
        parser = etree.XMLParser(ns_clean=True, recover=True, encoding='utf-8')
        xml_string = etree.XML(xml_string.encode('utf-8'), parser=parser)
        if not schema.validate(xml_string):
            for error in schema.error_log:
                result += f"\n\terror: {error.message}, line: {error.line}, column {error.column}"
    return result

@click.group()
def cli():
    pass



@cli.command(name="gen-md")
@click.argument('values-json-path', type=click.Path(exists=True))
@click.argument('service-type', type=click.Choice(SERVICE_TYPES_CLI, case_sensitive=True))
@click.argument('ngr-host', type=click.Choice(NGR_HOST_TYPES, case_sensitive=True))
@click.option('--output-dir', type=click.Path(exists=False), help="")
def generate_service_metadata_command(values_json_path, service_type, ngr_host, output_dir=""):
    """Generate metadata record.
    """
    if service_type == 'IN_JSON':
        ogc_service_type = get_ogc_service_type(values_json_path)
        if ogc_service_type not in SERVICE_TYPES:
            raise ValueError(f"invalid ogc_service_type in values-json {ogc_service_type}")
        service_type = ogc_service_type

    md_record = generate_service_metadata(values_json_path, service_type, ngr_host)
    validation_result = validate_service_metadata(md_record)
    
    if validation_result:
        print(f"metadata-generator error: generated metadata is invalid, validation message: {validation_result}")
        
    md_identifier = get_md_identifier(values_json_path)
    if output_dir:
        output_filename = f"{output_dir}/{md_identifier}_{service_type}.xml"
        if validation_result:
            output_filename = f"{output_dir}/{md_identifier}_{service_type}.invalid"

        with open(output_filename, 'w') as output:
            output.write(md_record)
    else:
        if validation_result:
            exit(1)
        print(md_record)

if __name__ == "__main__":
    # pylint: disable=no-value-for-parameter
    generate_service_metadata_command()
