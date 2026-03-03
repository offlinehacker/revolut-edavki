#!/usr/bin/python

import argparse
import datetime
import glob
import os
import re
import sys
import requests
import xml.etree.ElementTree
import csv
from difflib import SequenceMatcher
from xml.dom import minidom

bsRateXmlUrl = "https://www.bsi.si/_data/tecajnice/dtecbs-l.xml"
userAgent = 'revolut-davki'

def getCurrencyRate(dateStr, currency, rates):
    """Gets the currency rate for a given date and currency"""
    if currency == "CNH":
        currency = "CNY"
    if dateStr in rates and currency in rates[dateStr]:
        return float(rates[dateStr][currency])

    date = datetime.datetime.strptime(dateStr, "%Y%m%d")
    earliest_rate_date = min(
        datetime.datetime.strptime(rate_date, "%Y%m%d") for rate_date in rates
    )
    check_date = date - datetime.timedelta(days=1)
    while check_date >= earliest_rate_date:
        check_date_str = check_date.strftime("%Y%m%d")
        if check_date_str in rates and currency in rates[check_date_str]:
            print(
                "There is no exchange rate for "
                + str(dateStr)
                + ", using "
                + str(check_date_str)
            )
            return float(rates[check_date_str][currency])
        check_date -= datetime.timedelta(days=1)

    sys.exit("Error: There is no exchange rate for " + str(dateStr))


def parse_revolut_amount(value):
    """Parse Revolut amount strings (EUR/USD) into float"""
    if value is None:
        return 0.0
    normalized = (
        value.replace("\u202f", "")
        .replace("\xa0", "")
        .replace("US$", "")
        .replace("$", "")
        .replace("EUR", "")
        .replace("€", "")
        .replace(",", "")
        .replace("−", "-")
        .replace("–", "-")
        .strip()
    )
    if normalized in ["", "-", ".", "-."]:
        return 0.0
    return float(normalized)


def parse_revolut_date(value):
    """Parse Revolut dates in both date-only and datetime formats"""
    normalized = value.replace("\u202f", " ").replace("\xa0", " ").strip()
    for fmt in ["%b %d, %Y", "%b %d, %Y, %I:%M:%S %p"]:
        try:
            return datetime.datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {value}")

def parse_revolut_data(revolut_file, reportYear, rates):
    """Parse Revolut export file and convert to the internal format used by the script"""
    trades = {}
    dividends = []

    interests = []

    with open(revolut_file, "r", encoding="utf-8") as file:
        reader = csv.reader(file)
        current_section = None
        current_currency = ""

        for values in reader:
            if len(values) == 0:
                continue

            first_col = values[0].strip()
            if first_col == "":
                continue

            if first_col.startswith("Transactions for Brokerage Account sells"):
                current_section = "brokerage_sells"
                current_currency = first_col.split("-")[-1].strip() if "-" in first_col else ""
                continue

            if first_col.startswith("Transactions for Brokerage Account dividends"):
                current_section = "brokerage_dividends"
                current_currency = first_col.split("-")[-1].strip() if "-" in first_col else ""
                continue

            if first_col.startswith("Transactions for Flexible Cash Funds"):
                current_section = "flexible_cash"
                current_currency = first_col.split("-")[-1].strip() if "-" in first_col else ""
                continue

            if first_col.startswith("Transactions for "):
                current_section = None
                current_currency = ""
                continue

            if first_col.startswith("Portfolio"):
                continue

            if current_section == "brokerage_sells":
                if first_col == "Date acquired" or len(values) < 12:
                    continue

                date_acquired = parse_revolut_date(values[0])
                date_sold = parse_revolut_date(values[1])

                if date_sold.year != reportYear:
                    continue

                security_name = values[2]
                symbol = values[3]
                isin = values[4]
                quantity = float(values[6])
                if quantity == 0:
                    continue

                cost_basis = parse_revolut_amount(values[7])
                cost_basis_eur = parse_revolut_amount(values[8])
                proceeds = parse_revolut_amount(values[10])
                proceeds_eur = parse_revolut_amount(values[11])

                security_id = isin if isin else symbol

                open_trade = {
                    "conid": security_id,
                    "symbol": symbol,
                    "currency": current_currency,
                    "assetCategory": "STK",
                    "tradePrice": cost_basis / quantity,
                    "tradePriceEUR": cost_basis_eur / quantity,
                    "quantity": quantity,
                    "buySell": "BUY",
                    "tradeDate": date_acquired.strftime("%Y%m%d"),
                    "tradeTime": "0",
                    "transactionID": f"revolut_open_{symbol}_{date_acquired.strftime('%Y%m%d')}",
                    "ibOrderID": f"revolut_{symbol}_{date_acquired.strftime('%Y%m%d')}",
                    "openCloseIndicator": "O",
                    "isin": isin,
                    "description": security_name,
                    "assetType": "normal",
                    "positionType": "long",
                }

                close_trade = {
                    "conid": security_id,
                    "symbol": symbol,
                    "currency": current_currency,
                    "assetCategory": "STK",
                    "tradePrice": proceeds / quantity,
                    "tradePriceEUR": proceeds_eur / quantity,
                    "quantity": -quantity,
                    "buySell": "SELL",
                    "tradeDate": date_sold.strftime("%Y%m%d"),
                    "tradeTime": "0",
                    "transactionID": f"revolut_close_{symbol}_{date_sold.strftime('%Y%m%d')}",
                    "ibOrderID": f"revolut_{symbol}_{date_sold.strftime('%Y%m%d')}",
                    "openCloseIndicator": "C",
                    "isin": isin,
                    "description": security_name,
                    "assetType": "normal",
                    "positionType": "long",
                    "openTransactionIds": {open_trade["transactionID"]: quantity},
                }

                if security_id not in trades:
                    trades[security_id] = []

                trades[security_id].append(open_trade)
                trades[security_id].append(close_trade)
                continue

            if current_section == "brokerage_dividends":
                if first_col == "Date" or len(values) < 10:
                    continue

                date = parse_revolut_date(values[0])
                if date.year != reportYear:
                    continue

                security_name = values[1]
                symbol = values[2]
                isin = values[3]
                country = values[4]
                gross_amount = parse_revolut_amount(values[5])
                gross_amount_eur = parse_revolut_amount(values[6])
                withholding_tax = parse_revolut_amount(values[8]) if values[8].strip() else 0.0
                withholding_tax_eur = 0.0
                if len(values) > 9 and values[9].strip() != "":
                    withholding_tax_eur = parse_revolut_amount(values[9])
                elif gross_amount > 0:
                    withholding_tax_eur = withholding_tax / gross_amount * gross_amount_eur

                security_id = isin if isin else symbol

                dividend = {
                    "conid": security_id,
                    "symbol": symbol,
                    "currency": current_currency,
                    "amount": gross_amount,
                    "amountEUR": gross_amount_eur,
                    "securityID": security_id,
                    "isin": isin,
                    "description": security_name,
                    "dateTime": date.strftime("%Y%m%d"),
                    "transactionID": f"revolut_div_{symbol}_{date.strftime('%Y%m%d')}",
                    "tax": withholding_tax,
                    "taxEUR": withholding_tax_eur,
                    "country": country,
                    "name": security_name,
                    "address": f"{symbol} Inc., USA",
                    "taxNumber": "",
                }

                dividends.append(dividend)
                continue

            if current_section == "flexible_cash":
                if first_col == "Date" or len(values) < 3:
                    continue

                description = values[1].strip()
                if not description.startswith("Interest PAID"):
                    continue

                date = parse_revolut_date(values[0])
                if date.year != reportYear:
                    continue

                amount = parse_revolut_amount(values[2])
                if amount <= 0:
                    continue

                if current_currency == "EUR":
                    amount_eur = amount
                else:
                    rate = getCurrencyRate(date.strftime("%Y%m%d"), current_currency, rates)
                    amount_eur = amount / rate

                interests.append(
                    {
                        "accountId": "revolut",
                        "currency": current_currency,
                        "amount": amount,
                        "amountEUR": amount_eur,
                        "dateTime": date.strftime("%Y%m%d"),
                        "tax": 0.0,
                        "taxEUR": 0.0,
                        "identificationNumber": "305799582",
                        "payerName": "Revolut Securities Europe UAB",
                        "payerAddress": "Konstitucijos pr. 21B, LT-08105, Vilnius",
                        "payerCountry": "LT",
                        "sourceCountry": "LT",
                        "type": "7",
                    }
                )

    return trades, dividends, interests


def generate_doh_obr(
    taxpayerConfig,
    ibCashTransactionsList,
    rates,
    reportYear,
    test,
    testYearDiff,
    extraInterests=None,
):
    interests = []
    for ibCashTransactions in ibCashTransactionsList:
        if ibCashTransactions is None:
            continue

        for ibCashTransaction in ibCashTransactions:
            if ibCashTransaction.attrib["transactionID"] == "":
                continue
            if (
                ibCashTransaction.tag == "CashTransaction"
                and ibCashTransaction.get("dateTime").startswith(str(reportYear))
                and ibCashTransaction.get("type")
                in ["Broker Interest Received", "Broker Fees"]
            ):
                interests.append(
                    {
                        "accountId": ibCashTransaction.get("accountId"),
                        "currency": ibCashTransaction.get("currency"),
                        "amount": float(ibCashTransaction.get("amount")),
                        "description": ibCashTransaction.get("description"),
                        "dateTime": ibCashTransaction.get("dateTime"),
                        "transactionID": int(ibCashTransaction.get("transactionID")),
                        "tax": 0,
                    }
                )

        for ibCashTransaction in ibCashTransactions:
            if ibCashTransaction.attrib["transactionID"] == "":
                continue
            if (
                ibCashTransaction.tag == "CashTransaction"
                and ibCashTransaction.attrib["dateTime"].startswith(str(reportYear))
                and ibCashTransaction.attrib["type"] == "Withholding Tax"
                and ibCashTransaction.attrib["conid"] == ""
            ):
                potentiallyMatchingInterests = []
                for interest in interests:
                    if (
                        interest["tax"] == 0
                        and interest["dateTime"][0:8]
                        == ibCashTransaction.attrib["dateTime"][0:8]
                        and interest["currency"] == ibCashTransaction.attrib["currency"]
                        and int(interest["transactionID"])
                        < int(ibCashTransaction.attrib["transactionID"])
                        and interest["amount"] * float(ibCashTransaction.attrib["amount"])
                        < 0
                    ):
                        potentiallyMatchingInterests.append(interest)

                if len(potentiallyMatchingInterests) == 0:
                    print(
                        "WARNING: Cannot find a matching interest for %s - %s."
                        % (
                            ibCashTransaction.attrib["description"],
                            ibCashTransaction.attrib["amount"],
                        )
                    )
                    continue
                elif len(potentiallyMatchingInterests) == 1:
                    closestInterest = potentiallyMatchingInterests[0]
                else:
                    closestInterest = potentiallyMatchingInterests[0]
                    bestMatchLen = 0
                    for interest in potentiallyMatchingInterests:
                        taxDescription = ibCashTransaction.attrib["description"]
                        interestDescription = interest["description"]
                        match = SequenceMatcher(
                            None, taxDescription, interestDescription
                        ).find_longest_match(
                            0, len(taxDescription), 0, len(interestDescription)
                        )
                        if match.size > bestMatchLen:
                            bestMatchLen = match.size
                            closestInterest = interest

                closestInterestTax = -float(ibCashTransaction.attrib["amount"])
                closestInterest["tax"] += closestInterestTax

    if extraInterests is not None:
        interests.extend(extraInterests)

    for interest in interests:
        if "amountEUR" in interest and "taxEUR" in interest:
            continue
        if interest["currency"] == "EUR":
            interest["amountEUR"] = interest["amount"]
            interest["taxEUR"] = interest["tax"]
        else:
            rate = getCurrencyRate(interest["dateTime"][0:8], interest["currency"], rates)
            interest["amountEUR"] = interest["amount"] / rate
            interest["taxEUR"] = interest["tax"] / rate

    mergedInterests = []
    for interest in interests:
        merged = False
        interestType = interest.get("type", "2")
        interestPayer = interest.get("identificationNumber", "")
        interestCountry = interest.get("payerCountry", "")
        interestSourceCountry = interest.get("sourceCountry", interestCountry)
        for mergedInterest in mergedInterests:
            mergedType = mergedInterest.get("type", "2")
            mergedPayer = mergedInterest.get("identificationNumber", "")
            mergedCountry = mergedInterest.get("payerCountry", "")
            mergedSourceCountry = mergedInterest.get("sourceCountry", mergedCountry)
            if (
                interest["dateTime"][0:8] == mergedInterest["dateTime"][0:8]
                and interestType == mergedType
                and interestPayer == mergedPayer
                and interestCountry == mergedCountry
                and interestSourceCountry == mergedSourceCountry
            ):
                mergedInterest["amountEUR"] = (
                    mergedInterest["amountEUR"] + interest["amountEUR"]
                )
                mergedInterest["taxEUR"] = mergedInterest["taxEUR"] + interest["taxEUR"]
                merged = True
                break
        if merged is False:
            mergedInterests.append(interest)
    interests = mergedInterests

    envelope = xml.etree.ElementTree.Element(
        "Envelope", xmlns="http://edavki.durs.si/Documents/Schemas/Doh_Obr_2.xsd"
    )
    envelope.set(
        "xmlns:edp", "http://edavki.durs.si/Documents/Schemas/EDP-Common-1.xsd"
    )
    header = xml.etree.ElementTree.SubElement(envelope, "edp:Header")
    taxpayer = xml.etree.ElementTree.SubElement(header, "edp:taxpayer")
    xml.etree.ElementTree.SubElement(taxpayer, "edp:taxNumber").text = taxpayerConfig[
        "taxNumber"
    ]
    xml.etree.ElementTree.SubElement(
        taxpayer, "edp:taxpayerType"
    ).text = taxpayerConfig["taxpayerType"]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:name").text = taxpayerConfig["name"]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:address1").text = taxpayerConfig[
        "address1"
    ]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:city").text = taxpayerConfig["city"]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:postNumber").text = taxpayerConfig[
        "postNumber"
    ]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:postName").text = taxpayerConfig[
        "postName"
    ]
    xml.etree.ElementTree.SubElement(envelope, "edp:AttachmentList")
    xml.etree.ElementTree.SubElement(envelope, "edp:Signatures")
    body = xml.etree.ElementTree.SubElement(envelope, "body")
    xml.etree.ElementTree.SubElement(body, "edp:bodyContent")
    Doh_Obr = xml.etree.ElementTree.SubElement(body, "Doh_Obr")
    if test is True:
        dYear = str(reportYear + testYearDiff)
    else:
        dYear = str(reportYear)
    xml.etree.ElementTree.SubElement(Doh_Obr, "Period").text = dYear
    if test is True:
        xml.etree.ElementTree.SubElement(Doh_Obr, "DocumentWorkflowID").text = "I"
    else:
        xml.etree.ElementTree.SubElement(Doh_Obr, "DocumentWorkflowID").text = "O"
    xml.etree.ElementTree.SubElement(Doh_Obr, "Email").text = taxpayerConfig["email"]
    xml.etree.ElementTree.SubElement(Doh_Obr, "TelephoneNumber").text = taxpayerConfig[
        "telephoneNumber"
    ]
    xml.etree.ElementTree.SubElement(
        Doh_Obr, "ResidentOfRepublicOfSlovenia"
    ).text = taxpayerConfig["isResident"]
    xml.etree.ElementTree.SubElement(Doh_Obr, "Country").text = taxpayerConfig[
        "residentCountry"
    ]

    interests = sorted(interests, key=lambda k: k["dateTime"][0:8])
    for interest in interests:
        if round(interest["amountEUR"], 2) <= 0:
            continue

        Interest = xml.etree.ElementTree.SubElement(Doh_Obr, "Interest")
        identificationNumber = interest.get("identificationNumber", "")
        payerName = interest.get("payerName", "")
        payerAddress = interest.get("payerAddress", "")
        payerCountry = interest.get("payerCountry", "")
        sourceCountry = interest.get("sourceCountry", payerCountry)
        interestType = interest.get("type", "2")

        xml.etree.ElementTree.SubElement(Interest, "Date").text = (
            dYear + "-" + interest["dateTime"][4:6] + "-" + interest["dateTime"][6:8]
        )
        xml.etree.ElementTree.SubElement(
            Interest, "IdentificationNumber"
        ).text = identificationNumber
        xml.etree.ElementTree.SubElement(Interest, "Name").text = payerName
        xml.etree.ElementTree.SubElement(Interest, "Address").text = payerAddress
        xml.etree.ElementTree.SubElement(Interest, "Country").text = payerCountry
        xml.etree.ElementTree.SubElement(Interest, "Type").text = str(interestType)
        xml.etree.ElementTree.SubElement(Interest, "Value").text = "{0:.2f}".format(
            interest["amountEUR"]
        )
        xml.etree.ElementTree.SubElement(
            Interest, "ForeignTax"
        ).text = "{0:.2f}".format(interest["taxEUR"])
        xml.etree.ElementTree.SubElement(Interest, "Country2").text = sourceCountry

    xmlString = xml.etree.ElementTree.tostring(envelope)
    prettyXmlString = minidom.parseString(xmlString).toprettyxml(indent="\t")
    with open("Doh-Obr.xml", "w", encoding="utf-8") as f:
        f.write(prettyXmlString)
        print("Doh-Obr.xml created")

def main():
    if not os.path.isfile("taxpayer.xml"):
        print("Modify taxpayer.xml and add your data first!")
        f = open("taxpayer.xml", "w+", encoding="utf-8")
        f.write(
            "<taxpayer>\n"
            "   <taxNumber>12345678</taxNumber>\n"
            "   <taxpayerType>FO</taxpayerType>\n"
            "   <name>Janez Novak</name>\n"
            "   <address1>Slovenska 1</address1>\n"
            "   <city>Ljubljana</city>\n"
            "   <postNumber>1000</postNumber>\n"
            "   <postName>Ljubljana</postName>\n"
            "   <email>janez.novak@furs.si</email>\n"
            "   <telephoneNumber>01 123 45 67</telephoneNumber>\n"
            "   <residentCountry>SI</residentCountry>\n"
            "   <isResident>true</isResident>\n"
            "</taxpayer>"
        )
        exit(0)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--csv",
        metavar="csv-file",
        required=True,
        help="Path to Revolut consolidated CSV export file",
    )
    parser.add_argument(
        "-y",
        metavar="report-year",
        type=int,
        default=0,
        help="Report will be generated for the provided calendar year (defaults to "
        + str(datetime.date.today().year - 1)
        + ")",
    )
    parser.add_argument(
        "-t",
        help="Change trade dates to previous year (see README.md)",
        action="store_true",
    )
    parser.add_argument(
        "--ignore-foreign-tax",
        help="Set Doh-Div ForeignTax to 0.00 for all dividend entries",
        action="store_true",
    )

    args = parser.parse_args()
    test = args.t
    ignoreForeignTax = args.ignore_foreign_tax
    if args.y == 0:
        if test == True:
            reportYear = datetime.date.today().year
        else:
            reportYear = datetime.date.today().year - 1
    else:
        reportYear = int(args.y)

    if test == True:
        testYearDiff = reportYear - datetime.date.today().year - 1
    else:
        testYearDiff = 0

    """ Parse taxpayer information from the local taxpayer.xml file """
    taxpayer = xml.etree.ElementTree.parse("taxpayer.xml").getroot()
    taxpayerConfig = {
        "taxNumber": taxpayer.find("taxNumber").text,
        "taxpayerType": "FO",
        "name": taxpayer.find("name").text,
        "address1": taxpayer.find("address1").text,
        "city": taxpayer.find("city").text,
        "postNumber": taxpayer.find("postNumber").text,
        "postName": taxpayer.find("postName").text,
        "email": taxpayer.find("email").text,
        "telephoneNumber": taxpayer.find("telephoneNumber").text,
        "residentCountry": taxpayer.find("residentCountry").text,
        "isResident": taxpayer.find("isResident").text,
    }

    """ Merge data from local companies-local.xml and repo companies.xml into local companies.xml """
    companies = []
    companiesXmls = []
    if not os.path.isfile("companies-local.xml"):
        with open("companies-local.xml", "w") as f:
            f.write("<companies>\n\n</companies>")
    try:
        companiesXmls.append(xml.etree.ElementTree.parse("companies-local.xml").getroot())
    except:
        pass
    try:
        r = requests.get(
            "https://github.com/offlinehacker/revolut-davki/raw/master/companies.xml",
            headers={"User-Agent": userAgent},
            timeout=20,
        )
        companiesXmls.append(xml.etree.ElementTree.ElementTree(xml.etree.ElementTree.fromstring(r.content)).getroot())
    except:
        pass

    """ To ease the transition from companies.xml to companies-local.xml we will keep local changes to companies.xml for now.
        This part of code wil be removed later. """
    try:
        companiesXmls.append(xml.etree.ElementTree.parse("companies.xml").getroot())
    except:
        pass

    for cs in companiesXmls:
        for company in cs:
            c = {
                "isin": "",
                "symbol": company.find("symbol").text.strip(),
                "name": company.find("name").text.strip(),
                "taxNumber": "",
                "address": company.find("address").text.strip(),
                "country": company.find("country").text.strip(),
                "conid": None,
            }
            if company.find("isin") is not None and company.find("isin").text is not None:
                c["isin"] = company.find("isin").text.strip()
            if company.find("taxNumber") is not None and company.find("taxNumber").text is not None:
                c["taxNumber"] = company.find("taxNumber").text.strip()
            if company.find("conid") is not None and company.find("conid").text is not None:
                c["conid"] = company.find("conid").text.strip()
            if c["isin"] != "":
                for x in companies:
                    if x["isin"] != "" and x["isin"] == c["isin"]:
                        break
                    elif x["isin"] == "" and c["conid"] is not None and x["conid"] == c["conid"]:
                        x["isin"] = c["isin"]
                        break
                    elif x["isin"] == "" and c["symbol"] is not None and x["symbol"] == c["symbol"] and x["name"] == c["name"]:
                        x["isin"] = c["isin"]
                        break
                else:
                    companies.append(c)
                continue
            if c["conid"] is not None:
                for x in companies:
                    if x["conid"] is not None and x["conid"] == c["conid"]:
                        break
                    elif x["conid"] is None and c["symbol"] is not None and x["symbol"] == c["symbol"] and x["name"] == c["name"]:
                        x["conid"] = c["conid"]
                        break
                else:
                    companies.append(c)
                continue
            for x in companies:
                if x["symbol"] == c["symbol"]:
                    break
            else:
                companies.append(c)
    if len(companies) > 0:
        companies.sort(key=lambda x: x["symbol"])
        cs = xml.etree.ElementTree.Element("companies")
        for company in companies:
            c = xml.etree.ElementTree.SubElement(cs, "company")
            xml.etree.ElementTree.SubElement(c, "isin").text = company["isin"]
            if company["conid"] is not None and company["conid"] != "":
                xml.etree.ElementTree.SubElement(c, "conid").text = company["conid"]
            xml.etree.ElementTree.SubElement(c, "symbol").text = company["symbol"]
            xml.etree.ElementTree.SubElement(c, "name").text = company["name"]
            xml.etree.ElementTree.SubElement(c, "taxNumber").text = company["taxNumber"]
            xml.etree.ElementTree.SubElement(c, "address").text = company["address"]
            xml.etree.ElementTree.SubElement(c, "country").text = company["country"]
        tree = xml.etree.ElementTree.ElementTree(cs)
        xml.etree.ElementTree.indent(tree)
        tree.write("companies.xml")

    """ Creating daily exchange rates object """
    bsRateXmlFilename = (
        "bsrate-"
        + str(datetime.date.today().year)
        + str(datetime.date.today().month)
        + str(datetime.date.today().day)
        + ".xml"
    )
    if not os.path.isfile(bsRateXmlFilename):
        for file in glob.glob("bsrate-*.xml"):
            os.remove(file)
        r = requests.get(bsRateXmlUrl, headers={"User-Agent": userAgent}, timeout=20)
        open(bsRateXmlFilename, 'wb').write(r.content)
    bsRateXml = xml.etree.ElementTree.parse(bsRateXmlFilename).getroot()

    rates = {}
    for d in bsRateXml:
        date = d.attrib["datum"].replace("-", "")
        rates[date] = {}
        for r in d:
            currency = r.attrib["oznaka"]
            rates[date][currency] = r.text

    # Parse Revolut data
    print(f"Parsing Revolut data from {args.csv}...")
    trades, dividends, interests = parse_revolut_data(args.csv, reportYear, rates)

    if test == True:
        statementStartDate = str(reportYear + testYearDiff) + "0101"
        statementEndDate = str(reportYear + testYearDiff) + "1231"
    else:
        statementStartDate = str(reportYear) + "0101"
        statementEndDate = str(reportYear) + "1231"

    # Process trades and generate required XMLs
    
    # Categorize trades
    longNormalTrades = {}
    shortNormalTrades = {}
    longDerivateTrades = {}
    shortDerivateTrades = {}

    for securityID in trades:
        for trade in trades[securityID]:
            if trade["assetType"] == "normal" and trade["positionType"] == "long":
                if securityID not in longNormalTrades:
                    longNormalTrades[securityID] = []
                longNormalTrades[securityID].append(trade)
            elif trade["assetType"] == "normal" and trade["positionType"] == "short":
                if securityID not in shortNormalTrades:
                    shortNormalTrades[securityID] = []
                shortNormalTrades[securityID].append(trade)
            elif trade["assetType"] == "derivate" and trade["positionType"] == "long":
                if securityID not in longDerivateTrades:
                    longDerivateTrades[securityID] = []
                longDerivateTrades[securityID].append(trade)
            elif trade["assetType"] == "derivate" and trade["positionType"] == "short":
                if securityID not in shortDerivateTrades:
                    shortDerivateTrades[securityID] = []
                shortDerivateTrades[securityID].append(trade)

    # Generate Doh-KDVP.xml for normal stock trades
    envelope = xml.etree.ElementTree.Element(
        "Envelope", xmlns="http://edavki.durs.si/Documents/Schemas/Doh_KDVP_9.xsd"
    )
    envelope.set(
        "xmlns:edp", "http://edavki.durs.si/Documents/Schemas/EDP-Common-1.xsd"
    )
    header = xml.etree.ElementTree.SubElement(envelope, "edp:Header")
    taxpayer = xml.etree.ElementTree.SubElement(header, "edp:taxpayer")
    xml.etree.ElementTree.SubElement(taxpayer, "edp:taxNumber").text = taxpayerConfig[
        "taxNumber"
    ]
    xml.etree.ElementTree.SubElement(
        taxpayer, "edp:taxpayerType"
    ).text = taxpayerConfig["taxpayerType"]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:name").text = taxpayerConfig["name"]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:address1").text = taxpayerConfig[
        "address1"
    ]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:city").text = taxpayerConfig["city"]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:postNumber").text = taxpayerConfig[
        "postNumber"
    ]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:postName").text = taxpayerConfig[
        "postName"
    ]
    xml.etree.ElementTree.SubElement(envelope, "edp:AttachmentList")
    xml.etree.ElementTree.SubElement(envelope, "edp:Signatures")
    body = xml.etree.ElementTree.SubElement(envelope, "body")
    xml.etree.ElementTree.SubElement(body, "edp:bodyContent")
    Doh_KDVP = xml.etree.ElementTree.SubElement(body, "Doh_KDVP")
    KDVP = xml.etree.ElementTree.SubElement(Doh_KDVP, "KDVP")

    # Set document type
    if test == True:
        xml.etree.ElementTree.SubElement(KDVP, "DocumentWorkflowID").text = "I"
    else:
        xml.etree.ElementTree.SubElement(KDVP, "DocumentWorkflowID").text = "O"

    # Year and period
    if test:
        dYear = str(reportYear + testYearDiff)
    else:
        dYear = str(reportYear)

    xml.etree.ElementTree.SubElement(KDVP, "Year").text = dYear
    xml.etree.ElementTree.SubElement(KDVP, "PeriodStart").text = f"{dYear}-01-01"
    xml.etree.ElementTree.SubElement(KDVP, "PeriodEnd").text = f"{dYear}-12-31"

    # Resident information
    xml.etree.ElementTree.SubElement(KDVP, "IsResident").text = taxpayerConfig["isResident"]

    # Contact info
    xml.etree.ElementTree.SubElement(KDVP, "TelephoneNumber").text = taxpayerConfig["telephoneNumber"]

    # Security counts - important for the tax authority
    xml.etree.ElementTree.SubElement(KDVP, "SecurityCount").text = str(len(longNormalTrades))
    xml.etree.ElementTree.SubElement(KDVP, "SecurityShortCount").text = str(len(shortNormalTrades))
    xml.etree.ElementTree.SubElement(KDVP, "SecurityWithContractCount").text = "0"
    xml.etree.ElementTree.SubElement(KDVP, "SecurityWithContractShortCount").text = "0"
    xml.etree.ElementTree.SubElement(KDVP, "ShareCount").text = "0"
    xml.etree.ElementTree.SubElement(KDVP, "Email").text = taxpayerConfig["email"]

    tradeYearsInNormalReport = set()
    for securityID in longNormalTrades:
        trades = longNormalTrades[securityID]
        KDVPItem = xml.etree.ElementTree.SubElement(Doh_KDVP, "KDVPItem")
        InventoryListType = xml.etree.ElementTree.SubElement(
            KDVPItem, "InventoryListType"
        ).text = "PLVP"
        Name = xml.etree.ElementTree.SubElement(KDVPItem, "Name").text = trades[0][
            "description"
        ]
        HasForeignTax = xml.etree.ElementTree.SubElement(
            KDVPItem, "HasForeignTax"
        ).text = "false"
        HasLossTransfer = xml.etree.ElementTree.SubElement(
            KDVPItem, "HasLossTransfer"
        ).text = "false"
        ForeignTransfer = xml.etree.ElementTree.SubElement(
            KDVPItem, "ForeignTransfer"
        ).text = "false"
        TaxDecreaseConformance = xml.etree.ElementTree.SubElement(
            KDVPItem, "TaxDecreaseConformance"
        ).text = "false"
        Securities = xml.etree.ElementTree.SubElement(KDVPItem, "Securities")
        if "isin" in trades[0]:
            ISIN = xml.etree.ElementTree.SubElement(
                Securities, "ISIN"
            ).text = trades[0]["isin"]
        Code = xml.etree.ElementTree.SubElement(Securities, "Code").text = trades[0][
            "symbol"
        ][:10]
        if "description" in trades[0]:
            Name = xml.etree.ElementTree.SubElement(
                Securities, "Name"
            ).text = trades[0]["description"]
        IsFond = xml.etree.ElementTree.SubElement(Securities, "IsFond").text = "false"

        F8Value = 0
        n = -1
        for trade in trades:
            n += 1
            if test == True:
                tradeYear = int(trade["tradeDate"][0:4]) + testYearDiff
            else:
                tradeYear = int(trade["tradeDate"][0:4])
            tradeYearsInNormalReport.add(str(tradeYear))
            Row = xml.etree.ElementTree.SubElement(Securities, "Row")
            ID = xml.etree.ElementTree.SubElement(Row, "ID").text = str(n)
            if trade["quantity"] > 0:
                PurchaseSale = xml.etree.ElementTree.SubElement(Row, "Purchase")
                F1 = xml.etree.ElementTree.SubElement(PurchaseSale, "F1").text = (
                    str(tradeYear)
                    + "-"
                    + trade["tradeDate"][4:6]
                    + "-"
                    + trade["tradeDate"][6:8]
                )
                F2 = xml.etree.ElementTree.SubElement(PurchaseSale, "F2").text = "B"
                F3 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F3"
                ).text = "{0:.4f}".format(trade["quantity"])
                F4 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F4"
                ).text = "{0:.4f}".format(trade["tradePriceEUR"])
                F5 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F5"
                ).text = "0.0000"
            else:
                PurchaseSale = xml.etree.ElementTree.SubElement(Row, "Sale")
                F6 = xml.etree.ElementTree.SubElement(PurchaseSale, "F6").text = (
                    str(tradeYear)
                    + "-"
                    + trade["tradeDate"][4:6]
                    + "-"
                    + trade["tradeDate"][6:8]
                )
                F7 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F7"
                ).text = "{0:.4f}".format(-trade["quantity"])
                F9 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F9"
                ).text = "{0:.4f}".format(trade["tradePriceEUR"])
            F8Value += trade["quantity"]
            F8 = xml.etree.ElementTree.SubElement(
                Row, "F8"
            ).text = "{0:.4f}".format(F8Value)

    for securityID in shortNormalTrades:
        trades = shortNormalTrades[securityID]
        KDVPItem = xml.etree.ElementTree.SubElement(Doh_KDVP, "KDVPItem")
        InventoryListType = xml.etree.ElementTree.SubElement(
            KDVPItem, "InventoryListType"
        ).text = "PLVPSHORT"
        Name = xml.etree.ElementTree.SubElement(KDVPItem, "Name").text = trades[0][
            "description"
        ]
        HasForeignTax = xml.etree.ElementTree.SubElement(
            KDVPItem, "HasForeignTax"
        ).text = "false"
        HasLossTransfer = xml.etree.ElementTree.SubElement(
            KDVPItem, "HasLossTransfer"
        ).text = "false"
        ForeignTransfer = xml.etree.ElementTree.SubElement(
            KDVPItem, "ForeignTransfer"
        ).text = "false"
        TaxDecreaseConformance = xml.etree.ElementTree.SubElement(
            KDVPItem, "TaxDecreaseConformance"
        ).text = "false"
        SecuritiesShort = xml.etree.ElementTree.SubElement(KDVPItem, "SecuritiesShort")
        if "isin" in trades[0]:
            ISIN = xml.etree.ElementTree.SubElement(
                SecuritiesShort, "ISIN"
            ).text = trades[0]["isin"]
        Code = xml.etree.ElementTree.SubElement(SecuritiesShort, "Code").text = trades[
            0
        ]["symbol"][:10]
        if "description" in trades[0]:
            Name = xml.etree.ElementTree.SubElement(
                SecuritiesShort, "Name"
            ).text = trades[0]["description"]
        IsFond = xml.etree.ElementTree.SubElement(
            SecuritiesShort, "IsFond"
        ).text = "false"

        F8Value = 0
        n = -1
        for trade in trades:
            n += 1
            if test == True:
                tradeYear = int(trade["tradeDate"][0:4]) + testYearDiff
            else:
                tradeYear = int(trade["tradeDate"][0:4])
            tradeYearsInNormalReport.add(str(tradeYear))
            Row = xml.etree.ElementTree.SubElement(SecuritiesShort, "Row")
            ID = xml.etree.ElementTree.SubElement(Row, "ID").text = str(n)
            if trade["quantity"] > 0:
                PurchaseSale = xml.etree.ElementTree.SubElement(Row, "Purchase")
                F1 = xml.etree.ElementTree.SubElement(PurchaseSale, "F1").text = (
                    str(tradeYear)
                    + "-"
                    + trade["tradeDate"][4:6]
                    + "-"
                    + trade["tradeDate"][6:8]
                )
                F2 = xml.etree.ElementTree.SubElement(PurchaseSale, "F2").text = "A"
                F3 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F3"
                ).text = "{0:.4f}".format(trade["quantity"])
                F4 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F4"
                ).text = "{0:.4f}".format(trade["tradePriceEUR"])
                F5 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F5"
                ).text = "0.0000"
            else:
                PurchaseSale = xml.etree.ElementTree.SubElement(Row, "Sale")
                F6 = xml.etree.ElementTree.SubElement(PurchaseSale, "F6").text = (
                    str(tradeYear)
                    + "-"
                    + trade["tradeDate"][4:6]
                    + "-"
                    + trade["tradeDate"][6:8]
                )
                F7 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F7"
                ).text = "{0:.4f}".format(-trade["quantity"])
                F9 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F9"
                ).text = "{0:.4f}".format(trade["tradePriceEUR"])
            F8Value += trade["quantity"]
            F8 = xml.etree.ElementTree.SubElement(
                Row, "F8"
            ).text = "{0:.4f}".format(F8Value)

    xmlString = xml.etree.ElementTree.tostring(envelope)
    prettyXmlString = minidom.parseString(xmlString).toprettyxml(indent="\t")
    with open("Doh-KDVP.xml", "w", encoding="utf-8") as f:
        f.write(prettyXmlString)
        if tradeYearsInNormalReport:
            print(
                "Doh-KDVP.xml created (includes trades from years %s)"
                % ", ".join(sorted(tradeYearsInNormalReport))
            )
        else:
            print("Doh-KDVP.xml created (includes no trades)")

    # Generate D-IFI.xml for derivative trades
    envelope = xml.etree.ElementTree.Element(
        "Envelope", xmlns="http://edavki.durs.si/Documents/Schemas/D_IFI_4.xsd"
    )
    envelope.set(
        "xmlns:edp", "http://edavki.durs.si/Documents/Schemas/EDP-Common-1.xsd"
    )
    header = xml.etree.ElementTree.SubElement(envelope, "edp:Header")
    taxpayer = xml.etree.ElementTree.SubElement(header, "edp:taxpayer")
    xml.etree.ElementTree.SubElement(taxpayer, "edp:taxNumber").text = taxpayerConfig[
        "taxNumber"
    ]
    xml.etree.ElementTree.SubElement(
        taxpayer, "edp:taxpayerType"
    ).text = taxpayerConfig["taxpayerType"]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:name").text = taxpayerConfig["name"]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:address1").text = taxpayerConfig[
        "address1"
    ]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:city").text = taxpayerConfig["city"]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:postNumber").text = taxpayerConfig[
        "postNumber"
    ]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:postName").text = taxpayerConfig[
        "postName"
    ]
    workflow = xml.etree.ElementTree.SubElement(header, "edp:Workflow")
    if test == True:
        xml.etree.ElementTree.SubElement(workflow, "edp:DocumentWorkflowID").text = "I"
    else:
        xml.etree.ElementTree.SubElement(workflow, "edp:DocumentWorkflowID").text = "O"
    xml.etree.ElementTree.SubElement(envelope, "edp:AttachmentList")
    xml.etree.ElementTree.SubElement(envelope, "edp:Signatures")
    body = xml.etree.ElementTree.SubElement(envelope, "body")
    xml.etree.ElementTree.SubElement(body, "edp:bodyContent")
    difi = xml.etree.ElementTree.SubElement(body, "D_IFI")
    xml.etree.ElementTree.SubElement(difi, "PeriodStart").text = (
        statementStartDate[0:4]
        + "-"
        + statementStartDate[4:6]
        + "-"
        + statementStartDate[6:8]
    )
    xml.etree.ElementTree.SubElement(difi, "PeriodEnd").text = (
        statementEndDate[0:4]
        + "-"
        + statementEndDate[4:6]
        + "-"
        + statementEndDate[6:8]
    )
    xml.etree.ElementTree.SubElement(difi, "TelephoneNumber").text = taxpayerConfig[
        "telephoneNumber"
    ]
    xml.etree.ElementTree.SubElement(difi, "Email").text = taxpayerConfig["email"]

    tradeYearsInDerivateReport = set()
    n = 0
    for securityID in longDerivateTrades:
        trades = longDerivateTrades[securityID]
        n += 1
        TItem = xml.etree.ElementTree.SubElement(difi, "TItem")
        TypeId = xml.etree.ElementTree.SubElement(TItem, "TypeId").text = "PLIFI"
        
        # Revolut doesn't have different derivative types like IB,
        # but we'll keep the structure in case we need to add them later
        Type = xml.etree.ElementTree.SubElement(TItem, "Type").text = "04"
        TypeName = xml.etree.ElementTree.SubElement(
            TItem, "TypeName"
        ).text = "drugo"
        
        if "description" in trades[0]:
            Name = xml.etree.ElementTree.SubElement(TItem, "Name").text = trades[0][
                "description"
            ]
        Code = xml.etree.ElementTree.SubElement(TItem, "Code").text = trades[0][
            "symbol"
        ][:10]
        if "isin" in trades[0]:
            ISIN = xml.etree.ElementTree.SubElement(TItem, "ISIN").text = trades[0][
                "isin"
            ]
        HasForeignTax = xml.etree.ElementTree.SubElement(
            TItem, "HasForeignTax"
        ).text = "false"

        F8Value = 0
        for trade in trades:
            if test == True:
                tradeYear = int(trade["tradeDate"][0:4]) + testYearDiff
            else:
                tradeYear = int(trade["tradeDate"][0:4])
            tradeYearsInDerivateReport.add(str(tradeYear))
            TSubItem = xml.etree.ElementTree.SubElement(TItem, "TSubItem")
            if trade["quantity"] > 0:
                PurchaseSale = xml.etree.ElementTree.SubElement(TSubItem, "Purchase")
                F1 = xml.etree.ElementTree.SubElement(PurchaseSale, "F1").text = (
                    str(tradeYear)
                    + "-"
                    + trade["tradeDate"][4:6]
                    + "-"
                    + trade["tradeDate"][6:8]
                )
                F2 = xml.etree.ElementTree.SubElement(PurchaseSale, "F2").text = "A"
                F3 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F3"
                ).text = "{0:.4f}".format(trade["quantity"])
                F4 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F4"
                ).text = "{0:.4f}".format(trade["tradePriceEUR"])
                F9 = xml.etree.ElementTree.SubElement(PurchaseSale, "F9").text = "false"
            else:
                PurchaseSale = xml.etree.ElementTree.SubElement(TSubItem, "Sale")
                F5 = xml.etree.ElementTree.SubElement(PurchaseSale, "F5").text = (
                    str(tradeYear)
                    + "-"
                    + trade["tradeDate"][4:6]
                    + "-"
                    + trade["tradeDate"][6:8]
                )
                F6 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F6"
                ).text = "{0:.4f}".format(-trade["quantity"])
                F7 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F7"
                ).text = "{0:.4f}".format(trade["tradePriceEUR"])
            F8Value += trade["quantity"]
            F8 = xml.etree.ElementTree.SubElement(
                TSubItem, "F8"
            ).text = "{0:.4f}".format(F8Value)

    for securityID in shortDerivateTrades:
        trades = shortDerivateTrades[securityID]
        n += 1
        TItem = xml.etree.ElementTree.SubElement(difi, "TItem")
        TypeId = xml.etree.ElementTree.SubElement(TItem, "TypeId").text = "PLIFIShort"
        
        # Revolut doesn't have different derivative types like IB,
        # but we'll keep the structure in case we need to add them later
        Type = xml.etree.ElementTree.SubElement(TItem, "Type").text = "04"
        TypeName = xml.etree.ElementTree.SubElement(
            TItem, "TypeName"
        ).text = "drugo"
        
        if "description" in trades[0]:
            Name = xml.etree.ElementTree.SubElement(TItem, "Name").text = trades[0][
                "description"
            ]
        Code = xml.etree.ElementTree.SubElement(TItem, "Code").text = trades[0][
            "symbol"
        ][:10]
        if "isin" in trades[0]:
            ISIN = xml.etree.ElementTree.SubElement(TItem, "ISIN").text = trades[0][
                "isin"
            ]
        HasForeignTax = xml.etree.ElementTree.SubElement(
            TItem, "HasForeignTax"
        ).text = "false"

        F8Value = 0
        for trade in trades:
            if test == True:
                tradeYear = int(trade["tradeDate"][0:4]) + testYearDiff
            else:
                tradeYear = int(trade["tradeDate"][0:4])
            tradeYearsInDerivateReport.add(str(tradeYear))
            TShortSubItem = xml.etree.ElementTree.SubElement(TItem, "TShortSubItem")
            if trade["quantity"] > 0:
                PurchaseSale = xml.etree.ElementTree.SubElement(
                    TShortSubItem, "Purchase"
                )
                F4 = xml.etree.ElementTree.SubElement(PurchaseSale, "F4").text = (
                    str(tradeYear)
                    + "-"
                    + trade["tradeDate"][4:6]
                    + "-"
                    + trade["tradeDate"][6:8]
                )
                F5 = xml.etree.ElementTree.SubElement(PurchaseSale, "F5").text = "A"
                F6 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F6"
                ).text = "{0:.4f}".format(trade["quantity"])
                F7 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F7"
                ).text = "{0:.4f}".format(trade["tradePriceEUR"])
            else:
                PurchaseSale = xml.etree.ElementTree.SubElement(TShortSubItem, "Sale")
                F1 = xml.etree.ElementTree.SubElement(PurchaseSale, "F1").text = (
                    str(tradeYear)
                    + "-"
                    + trade["tradeDate"][4:6]
                    + "-"
                    + trade["tradeDate"][6:8]
                )
                F2 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F2"
                ).text = "{0:.4f}".format(-trade["quantity"])
                F3 = xml.etree.ElementTree.SubElement(
                    PurchaseSale, "F3"
                ).text = "{0:.4f}".format(trade["tradePriceEUR"])
                F9 = xml.etree.ElementTree.SubElement(PurchaseSale, "F9").text = "false"
            F8Value += trade["quantity"]
            F8 = xml.etree.ElementTree.SubElement(
                TShortSubItem, "F8"
            ).text = "{0:.4f}".format(F8Value)

    xmlString = xml.etree.ElementTree.tostring(envelope)
    prettyXmlString = minidom.parseString(xmlString).toprettyxml(indent="\t")
    with open("D-IFI.xml", "w", encoding="utf-8") as f:
        f.write(prettyXmlString)
        if tradeYearsInDerivateReport:
            print(
                "D-IFI.xml created (includes trades from years %s)"
                % ", ".join(sorted(tradeYearsInDerivateReport))
            )
        else:
            print("D-IFI.xml created (includes no trades)")

    # Generate Doh-Div.xml for dividends
    envelope = xml.etree.ElementTree.Element(
        "Envelope", xmlns="http://edavki.durs.si/Documents/Schemas/Doh_Div_3.xsd"
    )
    envelope.set(
        "xmlns:edp", "http://edavki.durs.si/Documents/Schemas/EDP-Common-1.xsd"
    )
    header = xml.etree.ElementTree.SubElement(envelope, "edp:Header")
    taxpayer = xml.etree.ElementTree.SubElement(header, "edp:taxpayer")
    xml.etree.ElementTree.SubElement(taxpayer, "edp:taxNumber").text = taxpayerConfig[
        "taxNumber"
    ]
    xml.etree.ElementTree.SubElement(
        taxpayer, "edp:taxpayerType"
    ).text = taxpayerConfig["taxpayerType"]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:name").text = taxpayerConfig["name"]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:address1").text = taxpayerConfig[
        "address1"
    ]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:city").text = taxpayerConfig["city"]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:postNumber").text = taxpayerConfig[
        "postNumber"
    ]
    xml.etree.ElementTree.SubElement(taxpayer, "edp:postName").text = taxpayerConfig[
        "postName"
    ]
    workflow = xml.etree.ElementTree.SubElement(header, "edp:Workflow")
    if test == True:
        xml.etree.ElementTree.SubElement(workflow, "edp:DocumentWorkflowID").text = "I"
    else:
        xml.etree.ElementTree.SubElement(workflow, "edp:DocumentWorkflowID").text = "O"
    xml.etree.ElementTree.SubElement(envelope, "edp:AttachmentList")
    xml.etree.ElementTree.SubElement(envelope, "edp:Signatures")
    body = xml.etree.ElementTree.SubElement(envelope, "body")
    Doh_Div = xml.etree.ElementTree.SubElement(body, "Doh_Div")
    if test == True:
        dYear = str(reportYear + testYearDiff)
    else:
        dYear = str(reportYear)
    xml.etree.ElementTree.SubElement(Doh_Div, "Period").text = dYear
    xml.etree.ElementTree.SubElement(Doh_Div, "EmailAddress").text = taxpayerConfig[
        "email"
    ]
    xml.etree.ElementTree.SubElement(Doh_Div, "PhoneNumber").text = taxpayerConfig[
        "telephoneNumber"
    ]
    xml.etree.ElementTree.SubElement(Doh_Div, "ResidentCountry").text = taxpayerConfig[
        "residentCountry"
    ]
    xml.etree.ElementTree.SubElement(Doh_Div, "IsResident").text = taxpayerConfig[
        "isResident"
    ]

    # Match companies information with dividends
    for dividend in dividends:
        for company in companies:
            if (('isin' in dividend and 'isin' in company and dividend['isin'] == company['isin']) or
                (dividend['symbol'] == company['symbol'])):
                
                # Copy tax information from company to dividend
                if 'taxNumber' in company and company['taxNumber']:
                    dividend['taxNumber'] = company['taxNumber']
                
                if 'country' in company and company['country']:
                    dividend['country'] = company['country']
                
                if 'name' in company and company['name']:
                    dividend['name'] = company['name']
                
                if 'address' in company and company['address']:
                    dividend['address'] = company['address']
                
                break
        
        # If no tax number is found, add a default one (common for US companies)
        if not dividend.get('taxNumber'):
            if dividend.get('country') == 'US':
                dividend['taxNumber'] = 'US12345678'  # A placeholder US tax ID

    dividends = sorted(dividends, key=lambda k: k["dateTime"][0:8])
    for dividend in dividends:
        if round(dividend["amountEUR"], 2) <= 0:
            continue
        foreignTaxEUR = 0.0 if ignoreForeignTax else dividend["taxEUR"]
        Dividend = xml.etree.ElementTree.SubElement(body, "Dividend")
        xml.etree.ElementTree.SubElement(Dividend, "Date").text = (
            dYear + "-" + dividend["dateTime"][4:6] + "-" + dividend["dateTime"][6:8]
        )
        if "taxNumber" in dividend and dividend["taxNumber"]:
            if len(dividend["taxNumber"]) > 12:
                dividend["taxNumber"] = re.sub(r'[^a-zA-Z0-9]+', "", dividend["taxNumber"])[0:12]
            xml.etree.ElementTree.SubElement(
                Dividend, "PayerIdentificationNumber"
            ).text = dividend["taxNumber"]
        if "name" in dividend:
            xml.etree.ElementTree.SubElement(Dividend, "PayerName").text = dividend[
                "name"
            ]
        else:
            xml.etree.ElementTree.SubElement(Dividend, "PayerName").text = dividend[
                "symbol"
            ]
        if "address" in dividend:
            xml.etree.ElementTree.SubElement(Dividend, "PayerAddress").text = dividend[
                "address"
            ]
        if "country" in dividend:
            xml.etree.ElementTree.SubElement(Dividend, "PayerCountry").text = dividend[
                "country"
            ]
        xml.etree.ElementTree.SubElement(Dividend, "Type").text = "1"
        xml.etree.ElementTree.SubElement(Dividend, "Value").text = "{0:.2f}".format(
            dividend["amountEUR"]
        )
        xml.etree.ElementTree.SubElement(
            Dividend, "ForeignTax"
        ).text = "{0:.2f}".format(foreignTaxEUR)
        if "country" in dividend:
            xml.etree.ElementTree.SubElement(Dividend, "SourceCountry").text = dividend[
                "country"
            ]
        if "reliefStatement" in dividend:
            xml.etree.ElementTree.SubElement(
                Dividend, "ReliefStatement"
            ).text = dividend["reliefStatement"]
        else:
            xml.etree.ElementTree.SubElement(Dividend, "ReliefStatement").text = ""

    xmlString = xml.etree.ElementTree.tostring(envelope)
    prettyXmlString = minidom.parseString(xmlString).toprettyxml(indent="\t")
    with open("Doh-Div.xml", "w", encoding="utf-8") as f:
        f.write(prettyXmlString)
        print("Doh-Div.xml created")

    # Generate Doh-Obr.xml for interest
    generate_doh_obr(
        taxpayerConfig,
        [],  # No cash transactions for interest in Revolut
        rates,
        reportYear,
        test,
        testYearDiff,
        interests,
    )

if __name__ == "__main__":
    main()
