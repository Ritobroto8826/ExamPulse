from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
import unittest
import pandas as pd
from uploads import read_score_upload


class UploadTests(unittest.TestCase):
    def test_valid_csv_and_excel(self):
        frame=pd.DataFrame([{"student":"one@example.test","subject":"Science","topic":"Electricity","exam":"Unit 1","exam_date":"2026-11-26","score":80}])
        self.assertEqual(len(read_score_upload(frame.to_csv(index=False).encode(),"scores.csv")),1)
        data=BytesIO();frame.to_excel(data,index=False)
        self.assertEqual(len(read_score_upload(data.getvalue(),"scores.xlsx")),1)

    def test_limit_and_unsupported_formats(self):
        with self.assertRaises(ValueError):read_score_upload(b'x'*(5*1024*1024+1),"large.csv")
        with self.assertRaises(ValueError):read_score_upload(b'x',"file.xlsm")
        data=("a,b\n"+"1,2\n"*1001).encode()
        with self.assertRaises(ValueError):read_score_upload(data,"rows.csv")

    def test_high_compression_workbook_rejected(self):
        data=BytesIO()
        with ZipFile(data,'w',ZIP_DEFLATED) as z:z.writestr('xl/worksheets/sheet1.xml','0'*(2*1024*1024))
        with self.assertRaisesRegex(ValueError,'compression'):
            read_score_upload(data.getvalue(),"unsafe.xlsx")


if __name__=='__main__':unittest.main()
